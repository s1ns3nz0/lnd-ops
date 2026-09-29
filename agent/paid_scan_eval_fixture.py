#!/usr/bin/env python3
"""Eval-only MCP server: same tool schemas as paid_scan_diagnostics, canned scenario outputs.

Holds no credentials and reaches no upstream. The active scenario name is read
per call from STATE_DIR/active; scenarios are SCENARIO_DIR/<name>.json.
"""

import json
import os
import re
import sys
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paid_scan_diagnostics as prod  # noqa: E402  (schemas and get_playbook are reused, never copied)

TOOLS = [prod.TOOL, prod.WORKLOAD_TOOL, prod.FUNNEL_TOOL, prod.PLAYBOOK_TOOL]
SCENARIO_NAME = re.compile(r"[a-z0-9-]{1,64}")
NOT_CONFIGURED = {"status": "unknown", "reason": "not_configured"}
MAX_SCENARIO_BYTES = 256 * 1024


def scenario_tools():
    """Tool outputs of the active scenario, or {} when unset, invalid or unreadable."""
    try:
        with open(os.path.join(os.environ.get("STATE_DIR", "/state"), "active"), encoding="ascii") as stream:
            name = stream.read(65).strip()
        if not SCENARIO_NAME.fullmatch(name):
            return {}
        with open(os.path.join(os.environ.get("SCENARIO_DIR", "/scenarios"), f"{name}.json"), "rb") as stream:
            raw = stream.read(MAX_SCENARIO_BYTES + 1)
        tools = json.loads(raw)["tools"] if len(raw) <= MAX_SCENARIO_BYTES else {}
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    return tools if isinstance(tools, dict) else {}


def call(name, arguments):
    if name == prod.PLAYBOOK_TOOL["name"]:
        return prod.get_playbook(arguments)
    if name == prod.TOOL["name"]:  # real argument rules, arguments otherwise ignored
        if not isinstance(arguments, dict) or set(arguments) != {"tenant_id", "order_id"}:
            raise ValueError("exactly tenant_id and order_id are required")
        prod.canonical_id(arguments["tenant_id"])
        prod.canonical_id(arguments["order_id"])
    elif arguments not in (None, {}):
        raise ValueError("no arguments are accepted")
    value = scenario_tools().get(name)
    return value if isinstance(value, dict) else NOT_CONFIGURED


class Handler(prod.Handler):
    """Inherits reply, /healthz and logging silence; only the MCP dispatch differs."""

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
                          "serverInfo": {"name": "paid-scan-eval-fixture", "version": "1.0.0"}}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "ping":
                result = {}
            elif method == "tools/call":
                params = request.get("params")
                if not isinstance(params, dict) or params.get("name") not in [t["name"] for t in TOOLS]:
                    raise ValueError()
                try:
                    result = {"content": [{"type": "text", "text": json.dumps(call(params["name"], params.get("arguments")))}]}
                except ValueError:
                    result = prod.invalid_arguments(next(t for t in TOOLS if t["name"] == params["name"]))
                except (OSError, RuntimeError):  # fixed text only; never surface exception details
                    result = {"content": [{"type": "text", "text": json.dumps({"status": "error", "reason": "tool_unavailable", "message": params["name"] + " could not reach its data source; treat as unknown, not healthy"})}], "isError": True}
            else:
                raise ValueError()
            self.reply(200, {"jsonrpc": "2.0", "id": request_id, "result": result})
        except (ValueError, TypeError, OSError):
            self.reply(200, {"jsonrpc": "2.0", "id": request_id,
                             "error": {"code": -32602, "message": "invalid diagnostic request"}})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
