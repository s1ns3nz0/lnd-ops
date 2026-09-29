#!/usr/bin/env python3
"""Minimal MCP gateway for constrained LND runbook operations.

Only fixed diagnostic queries and one harmless probe restart are exposed.  The
gateway deliberately has no generic kubectl, shell, PromQL, or LND RPC tool.
"""

import json
import math
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


NAMESPACES = {"lnd-regtest", "lnd-testnet", "lndops-monitoring", "lndops-falco", "lndops-agent"}
WORKLOAD_KINDS = {
    "pods": "api/v1/namespaces/{namespace}/pods",
    "events": "api/v1/namespaces/{namespace}/events",
    "persistentvolumeclaims": "api/v1/namespaces/{namespace}/persistentvolumeclaims",
    "statefulsets": "apis/apps/v1/namespaces/{namespace}/statefulsets",
}
SCENARIOS = {
    "channel_inactive": {
        "query": 'sum(lnd_channels_inactive_total{namespace="lnd-regtest"})',
        "alert": "LndOpsChannelInactive",
        "runbook": "channel-inactive.md",
        "cause": "one or more LND channels are inactive",
    },
    "pod_not_ready": {
        "query": 'sum(kube_pod_status_ready{namespace=~"lnd-regtest|lnd-testnet",condition="false"})',
        "alert": "LndOpsPodNotReady",
        "runbook": "pod-not-ready.md",
        "cause": "one or more protected workload pods are not ready",
    },
    "falco_event": {
        "query": 'sum(increase(falcosidekick_falco_events_total{rule="LND Ops Runtime Test Event"}[5m]))',
        "alert": "LndOpsFalcoRuntimeEvent",
        "runbook": "falco-runtime-event.md",
        "cause": "Falco observed a protected runtime event",
    },
}
RUNBOOKS = {name for name in os.environ.get("RUNBOOK_ALLOWLIST", "").split(",") if name}
PROMETHEUS = os.environ.get(
    "PROMETHEUS_URL", "http://lnd-ops-monitoring-kube-pr-prometheus.lndops-monitoring.svc:9090"
)
KUBE_HOST = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
KUBE_PORT = os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")
TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
CA_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
NAMESPACE_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
COOLDOWN_SECONDS = int(os.environ.get("ACTION_COOLDOWN_SECONDS", "300"))
MAX_LOG_BYTES = 16384
SECRET_PATTERNS = [
    re.compile(r"(?i)(macaroon|payment_request|payment_hash|preimage|seed|cipher_seed|wallet_password)\s*[:=]\s*\S+"),
    re.compile(r"\blntb[0-9a-z]+", re.I),
    re.compile(r"\b(?:02|03)[0-9a-f]{64}\b", re.I),
    re.compile(r"\b[0-9a-f]{64,}\b", re.I),
]


def redact(value):
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text[:MAX_LOG_BYTES]


def kube_request(path, method="GET", body=None):
    with open(TOKEN_PATH, encoding="utf-8") as stream:
        token = stream.read().strip()
    data = json.dumps(body).encode() if body is not None else None
    content_type = "application/merge-patch+json" if method == "PATCH" else "application/json"
    request = urllib.request.Request(
        f"https://{KUBE_HOST}:{KUBE_PORT}/{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": content_type},
    )
    with urllib.request.urlopen(request, context=ssl.create_default_context(cafile=CA_PATH), timeout=10) as response:
        return json.load(response)


def prometheus_query(query):
    url = f"{PROMETHEUS}/api/v1/query?{urllib.parse.urlencode({'query': query})}"
    with urllib.request.urlopen(url, timeout=10) as response:
        payload = json.load(response)
    if payload.get("status") != "success":
        raise RuntimeError("approved Prometheus query failed")
    result = payload.get("data", {}).get("result", [])
    return [{"metric": x.get("metric", {}), "value": x.get("value", [None, None])[1]} for x in result[:20]]


def audit(reason, action, outcome):
    namespace = open(NAMESPACE_PATH, encoding="utf-8").read().strip()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    name = f"runbook-agent-{time.time_ns()}"
    event = {
        "apiVersion": "v1", "kind": "Event",
        "metadata": {"name": name, "namespace": namespace},
        "involvedObject": {"apiVersion": "v1", "kind": "ServiceAccount", "name": "runbook-gateway", "namespace": namespace},
        "reason": reason, "message": redact(f"action={action} outcome={outcome}"),
        "type": "Normal" if outcome == "allowed" else "Warning",
        "firstTimestamp": now, "lastTimestamp": now, "count": 1,
        "source": {"component": "lnd-ops-runbook-gateway"},
    }
    return kube_request(f"api/v1/namespaces/{namespace}/events", "POST", event)


def tool_status(arguments):
    namespace = arguments.get("namespace", "")
    kind = arguments.get("kind", "")
    if namespace not in NAMESPACES or kind not in WORKLOAD_KINDS:
        raise ValueError("namespace or kind is outside the diagnostic allowlist")
    payload = kube_request(WORKLOAD_KINDS[kind].format(namespace=namespace))
    items = []
    for item in payload.get("items", [])[:50]:
        metadata, status = item.get("metadata", {}), item.get("status", {})
        entry = {"name": metadata.get("name"), "namespace": namespace}
        if kind == "events":
            entry.update(reason=item.get("reason"), message=redact(item.get("message", "")), type=item.get("type"))
        else:
            entry.update(phase=status.get("phase"), conditions=status.get("conditions", []), replicas=status.get("replicas"))
        items.append(entry)
    return {"kind": kind, "namespace": namespace, "items": items}


def tool_logs(arguments):
    namespace, pod = arguments.get("namespace", ""), arguments.get("pod", "")
    container = arguments.get("container", "")
    if namespace not in NAMESPACES or not re.fullmatch(r"[a-z0-9]([-a-z0-9.]*[a-z0-9])?", pod):
        raise ValueError("log target is outside the diagnostic allowlist")
    params = {"tailLines": "50", "timestamps": "true"}
    if container:
        params["container"] = container
    path = f"api/v1/namespaces/{namespace}/pods/{pod}/log?{urllib.parse.urlencode(params)}"
    with open(TOKEN_PATH, encoding="utf-8") as stream:
        token = stream.read().strip()
    request = urllib.request.Request(
        f"https://{KUBE_HOST}:{KUBE_PORT}/{path}", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(request, context=ssl.create_default_context(cafile=CA_PATH), timeout=10) as response:
        return {"namespace": namespace, "pod": pod, "logs": redact(response.read(MAX_LOG_BYTES).decode(errors="replace"))}


def tool_diagnose(arguments):
    name = arguments.get("scenario", "")
    if name not in SCENARIOS:
        raise ValueError("scenario is outside the diagnostic allowlist")
    scenario = SCENARIOS[name]
    result = prometheus_query(scenario["query"])
    active = any(float(row.get("value") or 0) > 0 for row in result)
    return {
        "scenario": name, "observed_facts": {"approved_query": scenario["query"], "result": result},
        "likely_cause": scenario["cause"] if active else "the selected signal is currently healthy",
        "confidence": "high" if result else "low", "alert": scenario["alert"],
        "matching_runbook": scenario["runbook"],
        "recommended_command": f"ops/verify-monitoring --profile {'regtest' if name != 'pod_not_ready' else 'testnet'}",
        "automation_eligible": name == "pod_not_ready", "signal_active": active,
    }


ROUTER_SIGNALS = {
    "wallet_active": ('lnd_ops_wallet_state{namespace="lnd-testnet",service="lnd-0",state="SERVER_ACTIVE"}', "lnd-wallet-state", 1),
    "chain_synced": ('lnd_chain_synced{namespace="lnd-testnet",service="lnd-0"}', "lndmon", 1),
    "connected_peers": ('lnd_peer_count{namespace="lnd-testnet",service="lnd-0"}', "lndmon", 1),
    "active_channels_all": ('lnd_channels_active_total{namespace="lnd-testnet",service="lnd-0"}', "lndmon", 2),
    "outbound_demo_sat": ('lnd_channels_bandwidth_outgoing_sat{namespace="lnd-testnet",service="lnd-0",status="active"}', "lndmon", 10000),
    "inbound_demo_sat": ('lnd_channels_bandwidth_incoming_sat{namespace="lnd-testnet",service="lnd-0",status="active"}', "lndmon", 10000),
    "backup_current": ('lnd_ops_scb_backup_current{namespace="lnd-testnet",service="lnd-0"}', "lnd-payments", 1),
}


def router_signal_query(metric, job):
    # Filter samples before summing. Missing/stale observations stay absent,
    # rather than turning into a misleading zero or a healthy default.
    up = f'up{{namespace="lnd-testnet",service="lnd-0",job="{job}"}}'
    return (f'sum(({metric} and (timestamp({metric}) > time() - 120)) '
            f'and on (namespace, service) (({up} == 1) and (timestamp({up}) > time() - 120)))')


def tool_router_diagnose(arguments):
    """Read fixed testnet operational signals; never assert full routing readiness."""
    if arguments:
        raise ValueError("Router diagnostics take no custom namespace, query, or action")
    facts = {}
    for name, (metric, job, minimum) in ROUTER_SIGNALS.items():
        query = router_signal_query(metric, job)
        fact = {"state": "unknown", "value": None, "minimum": minimum, "approved_query": query}
        try:
            rows = prometheus_query(query)
            if len(rows) == 1:
                value = float(rows[0]["value"])
                if math.isfinite(value) and value >= 0:
                    fact.update(state="observed" if value >= minimum else "attention", value=value)
        except (ValueError, TypeError, KeyError, OSError, RuntimeError, urllib.error.URLError):
            pass  # Keep unavailable evidence unknown; no fallback to cached health.
        fact["queried_at"] = time.time()
        facts[name] = fact
    attention = [name for name, fact in facts.items() if fact["state"] == "attention"]
    unknown = [name for name, fact in facts.items() if fact["state"] == "unknown"]
    return {
        "scope": "lnd-testnet/lnd-0", "observed_facts": facts,
        "likely_cause": "Some operational signals need attention" if attention else
                        "Operational evidence is incomplete" if unknown else "The sampled operational thresholds are met",
        "attention": attention, "unknown": unknown, "confidence": "low" if unknown else "medium",
        "matching_runbook": "router-operations.md", "recommended_command": "ops/verify-router --json",
        "automation_eligible": False, "routing_verified": False,
        "limitations": ["Samples are sequential, not an atomic snapshot",
                        "Active channel metrics include private channels; two distinct public peers are not proved",
                        "Aggregate 10000 sat liquidity is a demo threshold, not a constrained route estimate",
                        "Backup hash agreement does not prove an external copy, seed custody, or recovery",
                        "External P2P reachability and payer forwarding proof require separate verification",
                        "No recent traffic is required"],
    }


def tool_runbook(arguments):
    name = arguments.get("name", "")
    if name not in RUNBOOKS or not re.fullmatch(r"[a-z0-9-]+\.md", name):
        raise ValueError("runbook is outside the versioned allowlist")
    with open(f"/runbooks/{name}", encoding="utf-8") as stream:
        return {"name": name, "content": redact(stream.read())}


def tool_verify(_arguments):
    return {
        "prometheus_ready": bool(prometheus_query("up")),
        "probe": tool_status({"namespace": "lndops-agent", "kind": "pods"}),
        "automation_eligible": True,
    }


def tool_response(arguments):
    action = arguments.get("action", "")
    if action != "restart_diagnostic_probe":
        audit("RunbookActionDenied", action or "unspecified", "denied")
        return {"allowed": False, "reason": "action is not in the mutation allowlist", "audit_recorded": True}
    state = kube_request("api/v1/namespaces/lndops-agent/configmaps/runbook-action-state")
    last = int(state.get("data", {}).get("lastRestartEpoch", "0"))
    now = int(time.time())
    if now - last < COOLDOWN_SECONDS:
        audit("RunbookActionDenied", action, "cooldown")
        return {"allowed": False, "reason": "cooldown active", "retry_after_seconds": COOLDOWN_SECONDS - (now - last), "audit_recorded": True}
    kube_request(
        "apis/apps/v1/namespaces/lndops-agent/deployments/runbook-diagnostic-probe", "PATCH",
        {"spec": {"template": {"metadata": {"annotations": {"lnd-ops/restarted-at": str(now)}}}}},
    )
    kube_request(
        "api/v1/namespaces/lndops-agent/configmaps/runbook-action-state", "PATCH",
        {"data": {"lastRestartEpoch": str(now)}},
    )
    audit("RunbookActionAllowed", action, "allowed")
    return {"allowed": True, "action": action, "audit_recorded": True, "cooldown_seconds": COOLDOWN_SECONDS}


TOOLS = {
    "get_workload_status": (tool_status, {"type": "object", "required": ["namespace", "kind"], "properties": {"namespace": {"type": "string", "enum": sorted(NAMESPACES)}, "kind": {"type": "string", "enum": sorted(WORKLOAD_KINDS)}}}),
    "get_redacted_logs": (tool_logs, {"type": "object", "required": ["namespace", "pod"], "properties": {"namespace": {"type": "string", "enum": sorted(NAMESPACES)}, "pod": {"type": "string"}, "container": {"type": "string"}}}),
    "diagnose_incident": (tool_diagnose, {"type": "object", "required": ["scenario"], "properties": {"scenario": {"type": "string", "enum": sorted(SCENARIOS)}}}),
    "diagnose_testnet_router": (tool_router_diagnose, {"type": "object", "properties": {}, "additionalProperties": False}),
    "get_versioned_runbook": (tool_runbook, {"type": "object", "required": ["name"], "properties": {"name": {"type": "string", "enum": sorted(RUNBOOKS)}}}),
    "verify_health": (tool_verify, {"type": "object", "properties": {}}),
    "execute_allowlisted_response": (tool_response, {"type": "object", "required": ["action"], "properties": {"action": {"type": "string"}}}),
}


def arguments_message(schema):
    """Fixed, schema-derived hint for the model; never echoes what the caller sent."""
    props, required = schema.get("properties", {}), schema.get("required", [])
    if not props:
        return "Arguments must be an empty object {}"
    parts = [f"{k}{'' if k in required else '?'}: " + (f"one of {v['enum']}" if "enum" in v else v.get("type", "any"))
             for k, v in props.items()]
    return "Arguments must be {" + ", ".join(parts) + "}"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(redact(fmt % args), flush=True)

    def send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.send_json(200, {"status": "ready"} if self.path == "/healthz" else {"error": "not found"})

    def do_POST(self):
        if self.path != "/mcp":
            self.send_json(404, {"error": "not found"})
            return
        try:
            request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            method, request_id = request.get("method"), request.get("id")
            if method == "initialize":
                result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "lnd-ops-runbook-gateway", "version": "1.0.0"}}
            elif method == "notifications/initialized":
                self.send_response(202); self.end_headers(); return
            elif method == "tools/list":
                result = {"tools": [{"name": name, "description": fn.__doc__ or name, "inputSchema": schema} for name, (fn, schema) in TOOLS.items()]}
            elif method == "tools/call":
                params = request.get("params", {})
                if not isinstance(params, dict) or params.get("name") not in TOOLS:
                    raise ValueError("unknown tool")
                try:
                    value = TOOLS[params["name"]][0](params.get("arguments", {}))
                    result = {"content": [{"type": "text", "text": json.dumps(value, sort_keys=True)}]}
                except ValueError:  # tool execution error: let the model see it and self-correct
                    err = {"status": "error", "reason": "invalid_arguments", "message": arguments_message(TOOLS[params["name"]][1])}
                    result = {"content": [{"type": "text", "text": json.dumps(err, sort_keys=True)}], "isError": True}
            else:
                raise ValueError("unsupported MCP method")
            self.send_json(200, {"jsonrpc": "2.0", "id": request_id, "result": result})
        except (ValueError, OSError, RuntimeError, urllib.error.URLError) as exc:
            self.send_json(200, {"jsonrpc": "2.0", "id": request.get("id") if 'request' in locals() else None, "error": {"code": -32000, "message": redact(str(exc))}})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
