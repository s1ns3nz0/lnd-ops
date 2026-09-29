#!/usr/bin/env python3
"""Read-only, bounded access to a tenant-scoped paid-scan status projection."""

import http.client
import json
import math
import os
import re
import ssl
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode, urlsplit

MAX_RESPONSE_BYTES = 32768
FAILURE_REASONS = frozenset({
    "not_configured", "invalid_configuration", "access_denied", "not_found_or_not_visible",
    "upstream_unavailable", "invalid_response", "response_too_large", "identity_mismatch",
    "stale_or_future_observation", "kubernetes_unavailable", "prometheus_unavailable",
})


class Unavailable(Exception):
    """Fixed diagnostic reason, never an upstream body or credential."""


def canonical_id(value):
    if not isinstance(value, str) or len(value) != 36:
        raise ValueError("tenant_id and order_id must be canonical UUIDs")
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError()
    except ValueError:
        raise ValueError("tenant_id and order_id must be canonical UUIDs") from None
    return value


def fetch_projection(tenant_id, order_id):
    """GET one configured origin. No redirects, environment proxies or caller URL."""
    canonical_id(tenant_id)
    canonical_id(order_id)
    origin = os.environ.get("PAID_SCAN_DIAGNOSTICS_ORIGIN", "")
    if not origin:
        raise Unavailable("not_configured")
    connection = None
    try:
        parsed = urlsplit(origin)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ("", "/")):
            raise Unavailable("invalid_configuration")
        with open(os.environ["PAID_SCAN_DIAGNOSTICS_TOKEN_FILE"], encoding="ascii") as stream:
            token = stream.read(4097).strip()
        if not token or len(token) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise Unavailable("invalid_configuration")
        context = ssl.create_default_context(cafile=os.environ.get("PAID_SCAN_DIAGNOSTICS_CA_FILE") or None)
        connection = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=5, context=context)
        connection.request("GET", f"/internal/v1/diagnostics/tenants/{tenant_id}/orders/{order_id}",
                           headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            reasons = {401: "access_denied", 403: "access_denied", 404: "not_found_or_not_visible"}
            raise Unavailable(reasons.get(response.status, "upstream_unavailable"))
        if response.getheader("Content-Type", "").split(";")[0].strip() != "application/json":
            raise Unavailable("invalid_response")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise Unavailable("response_too_large")
        return json.loads(raw)
    except Unavailable:
        raise
    except (OSError, ValueError, KeyError, http.client.HTTPException):
        raise Unavailable("upstream_unavailable") from None
    finally:
        if connection is not None:
            connection.close()


STATES = {
    "order": {"awaiting_payment", "payment_pending", "paid", "expired", "payment_failed"},
    "challenge": {"issuing", "issued", "verifying", "pending", "settled", "failed"},
    "scan": {"queued", "running", "completed", "failed", "cancelled"},
    "dispatch": {"pending", "leased", "registered", "dispatched", "blocked", "failed"},
}
LIMITATIONS = [
    "Database observation only; current LND and Kubernetes Job state are not independently verified.",
    "A completed scan record does not prove that the user can retrieve its result.",
    "Aperture/SIEM correlation is not connected; payment_ref cannot be joined to a raw payment hash.",
]


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40 or not value.endswith("Z"):
        raise Unavailable("invalid_response")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp()
    except (ValueError, OverflowError):
        raise Unavailable("invalid_response") from None


REASON = re.compile(r"[a-z][a-z0-9_]{0,63}")
JOB_NAME = re.compile(r"scan-[0-9a-f]{20}")


def optional(section, key, pattern):
    value = section.get(key) if section else None
    if value is None:
        return None
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise Unavailable("invalid_response")
    return value


def project(payload, tenant_id, order_id, now):
    """Copy only typed status fields; never forward arbitrary upstream content."""
    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise Unavailable("invalid_response")
    if not {"order", "payment", "scan", "dispatch"} <= payload.keys():
        raise Unavailable("invalid_response")
    order = payload.get("order")
    if (payload.get("tenant_id") != tenant_id or not isinstance(order, dict)
            or order.get("id") != order_id or payload.get("source") != "tenant_database"):
        raise Unavailable("identity_mismatch")
    observed = timestamp(payload.get("observed_at"))
    if not -5 <= now - observed <= 30:
        raise Unavailable("stale_or_future_observation")

    def state(section, name, nullable=False):
        if section is None and nullable:
            return None
        if not isinstance(section, dict) or section.get("state") not in STATES[name]:
            raise Unavailable("invalid_response")
        return section["state"]

    payment = payload.get("payment")
    if not isinstance(payment, dict) or payment.get("rail") not in {"l402", "x402"}:
        raise Unavailable("invalid_response")
    if not {"challenge", "receipt_commit_state"} <= payment.keys():
        raise Unavailable("invalid_response")
    if type(payment.get("event_recorded")) is not bool:
        raise Unavailable("invalid_response")
    commit = payment.get("receipt_commit_state")
    if commit not in {None, "pending", "committed"}:
        raise Unavailable("invalid_response")
    facts = {
        "source": "tenant_database", "observed_at": payload["observed_at"],
        "order_state": state(order, "order"), "payment_rail": payment["rail"],
        "challenge_state": state(payment.get("challenge"), "challenge", True),
        "payment_event_recorded": payment["event_recorded"], "receipt_commit_state": commit,
        "scan_state": state(payload.get("scan"), "scan", True),
        "dispatch_state": state(payload.get("dispatch"), "dispatch", True),
        "result_recorded": False,
    }
    scan = payload.get("scan")
    if scan is not None and "result_available_at" not in scan:
        raise Unavailable("invalid_response")
    if scan and scan.get("result_available_at") is not None:
        if timestamp(scan["result_available_at"]) > observed + 5:
            raise Unavailable("invalid_response")
        facts["result_recorded"] = True
    dispatch = payload.get("dispatch")
    # Optional additive fields: older servers omit them.
    facts["scan_failure_reason"] = optional(scan, "failure_reason", REASON)
    facts["dispatch_reason"] = optional(dispatch, "reason", REASON)
    facts["dispatch_job_name"] = optional(dispatch, "job_name", JOB_NAME)
    if dispatch and dispatch.get("updated_at") is not None:
        age = observed - timestamp(dispatch["updated_at"])
        if age < -5:
            raise Unavailable("invalid_response")
        facts["dispatch_state_age_seconds"] = max(0, int(age))
    return facts


def diagnose(arguments, fetch=None, now=None):
    if not isinstance(arguments, dict) or set(arguments) != {"tenant_id", "order_id"}:
        raise ValueError("exactly tenant_id and order_id are required")
    tenant_id = canonical_id(arguments["tenant_id"])
    order_id = canonical_id(arguments["order_id"])
    result = {"tenant_id": tenant_id, "order_id": order_id, "read_only": True,
              "automation_eligible": False, "limitations": list(LIMITATIONS)}
    try:
        payload = (fetch or fetch_projection)(tenant_id, order_id)
        facts = project(payload, tenant_id, order_id, time.time() if now is None else now)
    except (Unavailable, TypeError, ValueError) as exc:
        # Type failures are schema failures, never raw exceptions or upstream content.
        reason = str(exc) if isinstance(exc, Unavailable) and str(exc) in FAILURE_REASONS else "invalid_response"
        return dict(result, status="unknown", reason=reason, observed_facts={}, next_check="restore_diagnostic_evidence")
    order, scan, dispatch = facts["order_state"], facts["scan_state"], facts["dispatch_state"]
    if (order == "paid" and not facts["payment_event_recorded"]) or (facts["result_recorded"] and scan != "completed"):
        stage, check = "inconsistent_records", "inspect_backend_reconciliation"
    elif order != "paid":
        stage, check = "payment", "inspect_payment_confirmation_and_receipt_commit"
    elif facts["receipt_commit_state"] == "pending" or facts["challenge_state"] not in {None, "settled"}:
        stage, check = "payment_records_need_review", "inspect_payment_confirmation_and_receipt_commit"
    elif scan is None:
        stage, check = "scan_creation", "inspect_backend_reconciliation"
    elif scan in {"failed", "cancelled"}:
        stage, check = "scan_terminal_without_result", "inspect_scan_attempt_and_job"
    elif scan == "completed":
        stage, check = ("result_recorded", "verify_result_retrieval") if facts["result_recorded"] else ("result_persistence", "inspect_result_ingestion")
    elif scan == "running":
        stage, check = "scan_running", "inspect_job_and_completion_callback"
    elif dispatch == "registered":
        stage, check = "dispatch_registration", "inspect_dispatcher_and_outbox"
    elif dispatch == "dispatched":
        stage, check = "worker_start", "inspect_job_scheduling_and_worker_start"
    else:
        stage, check = "dispatch", "inspect_dispatcher_and_outbox"
    if stage in {"worker_start", "scan_running", "scan_terminal_without_result"} and facts["dispatch_job_name"]:
        check += f"; get_opencti_workload_status can confirm Job {facts['dispatch_job_name']}"
    return dict(result, status="observed", stage=stage, next_check=check, observed_facts=facts)


KUBE_TOKEN_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/token"
KUBE_CA_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
KUBE_MAX_BYTES = 1 << 20
NAME = re.compile(r"[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9]{0,63}")
TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z")


def kube_get(path):
    """GET one Kubernetes API path with the pod's token. No redirects, proxies or caller URL."""
    connection = None
    try:
        with open(KUBE_TOKEN_FILE, encoding="ascii") as stream:
            token = stream.read(4097).strip()
        host, port = os.environ["KUBERNETES_SERVICE_HOST"], int(os.environ["KUBERNETES_SERVICE_PORT"])
        context = ssl.create_default_context(cafile=KUBE_CA_FILE)
        connection = http.client.HTTPSConnection(host, port, timeout=5, context=context)
        connection.request("GET", "/" + path, headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise Unavailable("kubernetes_unavailable")
        raw = response.read(KUBE_MAX_BYTES + 1)
        if len(raw) > KUBE_MAX_BYTES:
            raise Unavailable("response_too_large")
        try:
            return json.loads(raw)
        except ValueError:
            raise Unavailable("invalid_response") from None
    except Unavailable:
        raise
    except (OSError, ValueError, KeyError, http.client.HTTPException):
        raise Unavailable("kubernetes_unavailable") from None
    finally:
        if connection is not None:
            connection.close()


def word(value):
    """Reason/phase/kind strings: fixed shape or the literal "Other"; None stays None."""
    if value is None:
        return None
    return value if isinstance(value, str) and WORD.fullmatch(value) else "Other"


def name_of(value):
    return value if isinstance(value, str) and NAME.fullmatch(value) else None


def count(value):
    return value if type(value) is int and value >= 0 else 0


def when(value):
    return value if isinstance(value, str) and TIME.fullmatch(value) else None


def items(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise Unavailable("invalid_response")
    return [x for x in payload["items"] if isinstance(x, dict)]


def sub(obj, key):
    value = obj.get(key)
    return value if isinstance(value, dict) else {}


def workload_status(arguments, get=None, now=None):
    if arguments not in (None, {}):
        raise ValueError("no arguments are accepted")
    get = get or kube_get
    namespace = os.environ.get("OPENCTI_NAMESPACE", "")
    if not namespace or not NAME.fullmatch(namespace):
        return {"status": "unknown", "reason": "not_configured"}
    try:
        deployments, jobs, pods, events = [items(get(path)) for path in (
            f"apis/apps/v1/namespaces/{namespace}/deployments",
            f"apis/batch/v1/namespaces/{namespace}/jobs?labelSelector=app.kubernetes.io/name%3Dscanner-worker",
            f"api/v1/namespaces/{namespace}/pods",
            f"api/v1/namespaces/{namespace}/events?fieldSelector=type%3DWarning")]
        out = {"deployments": [], "jobs": [], "pods": [], "events": []}
        for item in deployments:
            meta, status = sub(item, "metadata"), sub(item, "status")
            if name_of(meta.get("name")):
                available = any(isinstance(c, dict) and c.get("type") == "Available" and c.get("status") == "True"
                                for c in status.get("conditions") or [])
                out["deployments"].append({
                    "name": meta["name"], "replicas": count(sub(item, "spec").get("replicas")),
                    "ready_replicas": count(status.get("readyReplicas")), "available": available})
        newest = lambda seq, key: sorted(seq, key=lambda x: str(key(x) or ""), reverse=True)
        for item in newest(jobs, lambda x: sub(x, "metadata").get("creationTimestamp")):
            meta, status = sub(item, "metadata"), sub(item, "status")
            if not name_of(meta.get("name")) or len(out["jobs"]) >= 20:
                continue
            done = next((c for c in status.get("conditions") or [] if isinstance(c, dict)
                         and c.get("type") in {"Complete", "Failed", "Suspended"} and c.get("status") == "True"), {})
            out["jobs"].append({
                "name": meta["name"], "active": count(status.get("active")),
                "succeeded": count(status.get("succeeded")), "failed": count(status.get("failed")),
                "condition": word(done.get("type")), "condition_reason": word(done.get("reason")),
                "start_time": when(status.get("startTime")), "completion_time": when(status.get("completionTime"))})
        for item in sorted(pods, key=lambda x: str(sub(x, "metadata").get("name"))):
            meta, status = sub(item, "metadata"), sub(item, "status")
            if not name_of(meta.get("name")) or status.get("phase") == "Succeeded" or len(out["pods"]) >= 50:
                continue
            owners = meta.get("ownerReferences")
            owner = owners[0] if isinstance(owners, list) and owners and isinstance(owners[0], dict) else {}
            owner_name = f"{word(owner.get('kind'))}/{name_of(owner.get('name'))}" if owner and name_of(owner.get("name")) else None
            containers = []
            for c in status.get("containerStatuses") or []:
                if not isinstance(c, dict) or not name_of(c.get("name")):
                    continue
                state, last = sub(c, "state"), sub(sub(c, "lastState"), "terminated")
                containers.append({
                    "name": c["name"], "ready": c.get("ready") is True, "restart_count": count(c.get("restartCount")),
                    "waiting_reason": word(sub(state, "waiting").get("reason")),
                    "terminated_reason": word(sub(state, "terminated").get("reason")),
                    "last_terminated_reason": word(last.get("reason"))})
            out["pods"].append({"name": meta["name"], "phase": word(status.get("phase")), "owner": owner_name,
                                "containers": containers})
        seen = lambda e: e.get("lastTimestamp") or e.get("eventTime") or sub(e, "metadata").get("creationTimestamp")
        for item in newest(events, seen):
            target = sub(item, "involvedObject")
            if not name_of(target.get("name")) or len(out["events"]) >= 30:
                continue
            out["events"].append({"reason": word(item.get("reason")), "object_kind": word(target.get("kind")),
                                  "object_name": target["name"], "count": count(item.get("count")),
                                  "last_seen": when(seen(item))})
    except (Unavailable, TypeError, ValueError, AttributeError, IndexError) as exc:
        reason = str(exc) if isinstance(exc, Unavailable) and str(exc) in FAILURE_REASONS else "invalid_response"
        return {"status": "unknown", "reason": reason}
    observed = time.gmtime(time.time() if now is None else now)
    return dict(out, status="observed", namespace=namespace, read_only=True,
                observed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", observed),
                limitations=["Kubernetes object state only; no logs.",
                             "Warning events expire (default 1h) and may be absent."])


PROM_DEFAULT = "http://lnd-ops-monitoring-kube-pr-prometheus.lndops-monitoring.svc:9090"
PROM_MAX_BYTES = 256 * 1024
_MINT = 'sum(increase(aperture_l402_mint_total{job="aperture",result="ok"}[15m]))'
_V = 'aperture_l402_verify_total{job="aperture",reason%s}'
FUNNEL_QUERIES = {
    "UP": 'max(up{job="aperture"})',
    "MINT_OK": _MINT,
    "MINT_FAILED": 'sum by (result) (increase(aperture_l402_mint_total{job="aperture",result!="ok"}[15m]))',
    "ACCEPTED": f'sum(increase({_V % "=\"accepted\""}[15m]))',
    "UNSETTLED": f'sum(increase({_V % "=\"invoice_unsettled\""}[15m]))',
    "NO_CREDENTIALS": f'sum(increase({_V % "=\"no_credentials\""}[15m]))',
    "LOOKUP_ERROR": f'sum(increase({_V % "=\"secret_lookup_error\""}[15m]))',
    "REJECTED": "sum by (reason) (increase(" + _V % '=~"bad_preimage|bad_signature|malformed_header|malformed_macaroon|secret_not_found|caveat_unsatisfied"' + "[15m]))",
}
NO_INVOICE_MIN = 2  # one tokenless request may sit at the window edge before its invoice is minted
MINT_RESULTS = frozenset({"challenge_failed", "identifier_failed", "secret_failed", "macaroon_failed", "caveat_failed"})
REJECT_REASONS = frozenset({"bad_preimage", "bad_signature", "malformed_header", "malformed_macaroon",
                            "secret_not_found", "caveat_unsatisfied"})
FUNNEL_LIMITATIONS = [
    "L402 scheme only. MPP (authscheme mpp or l402+mpp) and the x402 rail are not counted; no_l402_traffic means no L402 traffic, not no payments.",
    "Counters reset when Aperture restarts; increase() compensates but a restart inside the window can hide or blur events.",
    "One Aperture instance in opencti-paid-scan-e2e only.",
    "Low E2E traffic: counts, not ratios, drive the verdict.",
    "Rejected tokens are a security signal, not proof of attack.",
]


def prom_query(query):
    """GET one fixed-shape instant query. No redirects, proxies, TLS or caller URL."""
    connection = None
    try:
        parsed = urlsplit(os.environ.get("PROMETHEUS_URL") or PROM_DEFAULT)
        if (parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
            raise Unavailable("prometheus_unavailable")
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=5)
        connection.request("GET", "/api/v1/query?" + urlencode({"query": query}), headers={"Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise Unavailable("prometheus_unavailable")
        raw = response.read(PROM_MAX_BYTES + 1)
        if len(raw) > PROM_MAX_BYTES:
            raise Unavailable("prometheus_unavailable")
        payload = json.loads(raw)
        result = payload["data"]["result"]
        if payload["status"] != "success" or not isinstance(result, list):
            raise Unavailable("prometheus_unavailable")
        return result
    except Unavailable:
        raise
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
        raise Unavailable("prometheus_unavailable") from None
    finally:
        if connection is not None:
            connection.close()


def _series(rows, label=None, allowed=frozenset()):
    """Vector -> total, or {allowlisted label: total} with unknown labels folded into "other"."""
    totals = {}
    for row in rows:
        metric, value = row["metric"], row["value"]
        if not isinstance(metric, dict) or not isinstance(value, list) or len(value) != 2:
            raise ValueError()
        number = float(value[1])
        if not math.isfinite(number):
            raise ValueError()
        key = None
        if label:
            key = metric.get(label)
            key = key if key in allowed else "other"
        totals[key] = totals.get(key, 0.0) + number
    whole = lambda x: int(max(0.0, x) + 0.5)  # round half up, clamp negatives
    if label:
        return {k: whole(v) for k, v in sorted(totals.items()) if whole(v) > 0}
    return whole(sum(totals.values()))


def funnel_status(arguments, query=None, now=None):
    if arguments not in (None, {}):
        raise ValueError("no arguments are accepted")
    query = query or prom_query
    try:
        raw = {name: query(q) for name, q in FUNNEL_QUERIES.items()}
        if not raw["UP"]:
            return {"status": "unknown", "reason": "aperture_not_scraped"}
        if _series(raw["UP"]) < 1:
            return {"status": "unknown", "reason": "aperture_not_scraped"}
        issued, accepted, unsettled, lookup = (_series(raw[k]) for k in ("MINT_OK", "ACCEPTED", "UNSETTLED", "LOOKUP_ERROR"))
        tokenless = _series(raw["NO_CREDENTIALS"])
        failed = _series(raw["MINT_FAILED"], "result", MINT_RESULTS)
        rejected = _series(raw["REJECTED"], "reason", REJECT_REASONS)
    except Exception:  # fail closed on any query/shape error; never surface raw text
        return {"status": "unknown", "reason": "prometheus_unavailable"}
    signals = [f"mint_failed:{k}" for k in failed] + (["secret_lookup_error"] if lookup else [])
    if tokenless >= NO_INVOICE_MIN and not issued and not failed:
        signals.append("requests_without_invoice")
    total_rejected = sum(rejected.values())
    if signals:
        verdict = "incident"
    elif not (issued or accepted or unsettled or total_rejected or tokenless):
        verdict = "no_l402_traffic"
    elif tokenless == 1 and not (issued or accepted or unsettled or total_rejected):
        verdict = "inconclusive"
    else:
        verdict = "healthy"
    observed = time.gmtime(time.time() if now is None else now)
    return {"status": "observed", "verdict": verdict, "incident_signals": signals,
            "challenges_issued": issued, "requests_without_token": tokenless, "mint_failed": failed, "accepted": accepted,
            "invoice_unsettled": unsettled, "secret_lookup_error": lookup, "rejected": rejected,
            "security_signal": total_rejected > 0, "scope": "l402", "window": "15m", "read_only": True,
            "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", observed), "limitations": list(FUNNEL_LIMITATIONS)}


TOOL = {
    "name": "diagnose_paid_order",
    "description": "Read one tenant-scoped order projection to locate payment, dispatch or result stage. Database facts only; no automatic repair.",
    "inputSchema": {"type": "object", "required": ["tenant_id", "order_id"], "additionalProperties": False,
                    "properties": {key: {"type": "string", "format": "uuid"} for key in ("tenant_id", "order_id")}},
}

WORKLOAD_TOOL = {
    "name": "get_opencti_workload_status",
    "description": "Read Deployment, scanner Job, Pod and Warning Event state in the OpenCTI namespace. Object state only; no logs or messages.",
    "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
}

FUNNEL_TOOL = {
    "name": "diagnose_l402_funnel",
    "description": "Read fixed Aperture L402 counters from Prometheus (15m window) to judge challenge issuance and token verification. Verdict is incident | inconclusive | no_l402_traffic | healthy. Counts only; no per-request data.",
    "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
}


class Handler(BaseHTTPRequestHandler):
    """One-tool MCP surface, kept separate from legacy probe restart tools."""
    def log_message(self, *args):
        pass  # Request paths and bodies are not an operational log contract.

    def reply(self, status, payload=None):
        body = json.dumps(payload).encode() if payload is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.reply(200 if self.path == "/healthz" else 404,
                   {"status": "ready", "upstream_verified": False} if self.path == "/healthz" else {})

    def do_POST(self):
        self.connection.settimeout(10)
        if self.path != "/mcp":
            return self.reply(404, {})
        request_id = None
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096 or self.headers.get("Transfer-Encoding"):
                return self.reply(413, {})
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                raise ValueError()
            request_id = request.get("id")
            if type(request_id) not in (int, str, type(None)) or (isinstance(request_id, str) and len(request_id) > 64):
                request_id = None
                raise ValueError()
            method = request.get("method")
            if method == "notifications/initialized":
                return self.reply(202)
            if method == "initialize":
                result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "paid-scan-diagnostics", "version": "1.0.0"}}
            elif method == "tools/list":
                result = {"tools": [TOOL, WORKLOAD_TOOL, FUNNEL_TOOL]}
            elif method == "ping":
                result = {}
            elif method == "tools/call":
                params = request.get("params")
                if not isinstance(params, dict) or params.get("name") not in (TOOL["name"], WORKLOAD_TOOL["name"], FUNNEL_TOOL["name"]):
                    raise ValueError()
                run = {TOOL["name"]: diagnose, WORKLOAD_TOOL["name"]: workload_status, FUNNEL_TOOL["name"]: funnel_status}[params["name"]]
                value = run(params.get("arguments"))
                result = {"content": [{"type": "text", "text": json.dumps(value)}]}
            else:
                raise ValueError()
            self.reply(200, {"jsonrpc": "2.0", "id": request_id, "result": result})
        except (ValueError, TypeError, OSError):
            self.reply(200, {"jsonrpc": "2.0", "id": request_id,
                             "error": {"code": -32602, "message": "invalid diagnostic request"}})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
