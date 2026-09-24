#!/usr/bin/env python3
"""Minimal MCP gateway for constrained LND runbook operations.

Only fixed diagnostic queries and one harmless probe restart are exposed.  The
gateway deliberately has no generic kubectl, shell, PromQL, or LND RPC tool.
"""

import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


NAMESPACES = {"lnd-regtest", "lnd-testnet", "lnd-monitoring", "falco", "lnd-agent"}
WORKLOAD_KINDS = {
    "pods": "api/v1/namespaces/{namespace}/pods",
    "events": "api/v1/namespaces/{namespace}/events",
    "persistentvolumeclaims": "api/v1/namespaces/{namespace}/persistentvolumeclaims",
    "statefulsets": "apis/apps/v1/namespaces/{namespace}/statefulsets",
}
SCENARIOS = {
    "channel_inactive": {
        "query": 'sum(lnd_channels_inactive_total{namespace=~"lnd-regtest|lnd-testnet"})',
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
    "PROMETHEUS_URL", "http://lnd-ops-monitoring-kube-pr-prometheus.lnd-monitoring.svc:9090"
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
    request = urllib.request.Request(
        f"https://{KUBE_HOST}:{KUBE_PORT}/{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/merge-patch+json"},
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
    name = f"runbook-agent-{int(time.time())}"
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


def tool_runbook(arguments):
    name = arguments.get("name", "")
    if name not in RUNBOOKS or not re.fullmatch(r"[a-z0-9-]+\.md", name):
        raise ValueError("runbook is outside the versioned allowlist")
    with open(f"/runbooks/{name}", encoding="utf-8") as stream:
        return {"name": name, "content": redact(stream.read())}


def tool_verify(_arguments):
    return {
        "prometheus_ready": bool(prometheus_query("up")),
        "probe": tool_status({"namespace": "lnd-agent", "kind": "pods"}),
        "automation_eligible": True,
    }


def tool_response(arguments):
    action = arguments.get("action", "")
    if action != "restart_diagnostic_probe":
        audit("RunbookActionDenied", action or "unspecified", "denied")
        return {"allowed": False, "reason": "action is not in the mutation allowlist", "audit_recorded": True}
    state = kube_request("api/v1/namespaces/lnd-agent/configmaps/runbook-action-state")
    last = int(state.get("data", {}).get("lastRestartEpoch", "0"))
    now = int(time.time())
    if now - last < COOLDOWN_SECONDS:
        audit("RunbookActionDenied", action, "cooldown")
        return {"allowed": False, "reason": "cooldown active", "retry_after_seconds": COOLDOWN_SECONDS - (now - last), "audit_recorded": True}
    kube_request(
        "apis/apps/v1/namespaces/lnd-agent/deployments/runbook-diagnostic-probe", "PATCH",
        {"spec": {"template": {"metadata": {"annotations": {"lnd-ops/restarted-at": str(now)}}}}},
    )
    kube_request(
        "api/v1/namespaces/lnd-agent/configmaps/runbook-action-state", "PATCH",
        {"data": {"lastRestartEpoch": str(now)}},
    )
    audit("RunbookActionAllowed", action, "allowed")
    return {"allowed": True, "action": action, "audit_recorded": True, "cooldown_seconds": COOLDOWN_SECONDS}


TOOLS = {
    "get_workload_status": (tool_status, {"type": "object", "required": ["namespace", "kind"], "properties": {"namespace": {"type": "string", "enum": sorted(NAMESPACES)}, "kind": {"type": "string", "enum": sorted(WORKLOAD_KINDS)}}}),
    "get_redacted_logs": (tool_logs, {"type": "object", "required": ["namespace", "pod"], "properties": {"namespace": {"type": "string", "enum": sorted(NAMESPACES)}, "pod": {"type": "string"}, "container": {"type": "string"}}}),
    "diagnose_incident": (tool_diagnose, {"type": "object", "required": ["scenario"], "properties": {"scenario": {"type": "string", "enum": sorted(SCENARIOS)}}}),
    "get_versioned_runbook": (tool_runbook, {"type": "object", "required": ["name"], "properties": {"name": {"type": "string", "enum": sorted(RUNBOOKS)}}}),
    "verify_health": (tool_verify, {"type": "object", "properties": {}}),
    "execute_allowlisted_response": (tool_response, {"type": "object", "required": ["action"], "properties": {"action": {"type": "string"}}}),
}


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
                if params.get("name") not in TOOLS:
                    raise ValueError("unknown tool")
                value = TOOLS[params["name"]][0](params.get("arguments", {}))
                result = {"content": [{"type": "text", "text": json.dumps(value, sort_keys=True)}]}
            else:
                raise ValueError("unsupported MCP method")
            self.send_json(200, {"jsonrpc": "2.0", "id": request_id, "result": result})
        except (ValueError, OSError, RuntimeError, urllib.error.URLError) as exc:
            self.send_json(200, {"jsonrpc": "2.0", "id": request.get("id") if 'request' in locals() else None, "error": {"code": -32000, "message": redact(str(exc))}})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
