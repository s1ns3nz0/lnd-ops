import importlib.util
import json
import pathlib
import threading
import urllib.error
import urllib.request
import unittest
from unittest import mock


MODULE_PATH = pathlib.Path(__file__).parents[1] / "agent/runbook_gateway.py"
SPEC = importlib.util.spec_from_file_location("runbook_gateway", MODULE_PATH)
gateway = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gateway)


class RunbookGatewayTests(unittest.TestCase):
    def test_redacts_lightning_secrets(self):
        text = gateway.redact("wallet_password=hunter2 payment_request=lntb1abc payment_hash=" + "a" * 64)
        self.assertNotIn("hunter2", text)
        self.assertNotIn("lntb1abc", text)
        self.assertNotIn("a" * 64, text)

    def test_tool_surface_has_no_generic_execution(self):
        self.assertEqual(set(gateway.TOOLS), {
            "get_workload_status", "get_redacted_logs", "diagnose_incident",
            "get_versioned_runbook", "verify_health", "execute_allowlisted_response",
            "diagnose_testnet_router",
        })
        self.assertFalse(any("shell" in name or "kubectl" in name or "promql" in name for name in gateway.TOOLS))
        self.assertEqual(gateway.SCENARIOS["channel_inactive"]["query"], 'sum(lnd_channels_inactive_total{namespace="lnd-regtest"})')

    @mock.patch.object(gateway, "kube_request")
    @mock.patch.object(gateway, "prometheus_query")
    def test_idle_router_operational_signals_do_not_claim_routing_proof(self, query, kube):
        query.side_effect = [[{"value": minimum}] for _, _, minimum in gateway.ROUTER_SIGNALS.values()]
        result = gateway.tool_router_diagnose({})
        self.assertEqual(result["attention"], [])
        self.assertEqual(result["unknown"], [])
        self.assertFalse(result["routing_verified"])
        self.assertFalse(result["automation_eligible"])
        kube.assert_not_called()

    @mock.patch.object(gateway, "prometheus_query")
    def test_missing_nan_negative_or_failed_queries_are_unknown(self, query):
        query.side_effect = [[], [{"value": "NaN"}], [{"value": "-1"}], RuntimeError("offline"),
                             [{"value": "bad"}], [{"value": "1"}, {"value": "2"}], [{"value": "Inf"}]]
        result = gateway.tool_router_diagnose({})
        self.assertEqual(set(result["unknown"]), set(gateway.ROUTER_SIGNALS))
        self.assertEqual(result["confidence"], "low")

    @mock.patch.object(gateway, "prometheus_query", return_value=[{"value": "0"}])
    def test_observed_zero_requires_attention_not_unknown(self, query):
        result = gateway.tool_router_diagnose({})
        self.assertEqual(set(result["attention"]), set(gateway.ROUTER_SIGNALS))
        self.assertEqual(result["unknown"], [])

    @mock.patch.object(gateway, "prometheus_query")
    def test_router_query_override_is_rejected_before_io(self, query):
        with self.assertRaises(ValueError):
            gateway.tool_router_diagnose({"query": "up"})
        query.assert_not_called()

    @mock.patch.object(gateway, "audit")
    def test_forbidden_action_is_denied_and_audited(self, audit):
        result = gateway.tool_response({"action": "unlock_wallet"})
        self.assertEqual(result, {"allowed": False, "reason": "action is not in the mutation allowlist", "audit_recorded": True})
        audit.assert_called_once_with("RunbookActionDenied", "unlock_wallet", "denied")

    @mock.patch.object(gateway, "time")
    @mock.patch.object(gateway, "audit")
    @mock.patch.object(gateway, "kube_request")
    def test_cooldown_stops_repeat_restart(self, kube_request, audit, fake_time):
        fake_time.time.return_value = 1000
        fake_time.time_ns.return_value = 1000000000000
        kube_request.return_value = {"data": {"lastRestartEpoch": "900"}}
        result = gateway.tool_response({"action": "restart_diagnostic_probe"})
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "cooldown active")
        audit.assert_called_once_with("RunbookActionDenied", "restart_diagnostic_probe", "cooldown")

    @mock.patch.object(gateway, "time")
    @mock.patch.object(gateway, "audit")
    @mock.patch.object(gateway, "kube_request")
    def test_allowlisted_restart_is_narrow_and_audited(self, kube_request, audit, fake_time):
        fake_time.time.return_value = 1000
        kube_request.side_effect = [{"data": {"lastRestartEpoch": "0"}}, {}, {}]
        result = gateway.tool_response({"action": "restart_diagnostic_probe"})
        self.assertTrue(result["allowed"])
        paths = [call.args[0] for call in kube_request.call_args_list]
        self.assertIn("apis/apps/v1/namespaces/lndops-agent/deployments/runbook-diagnostic-probe", paths)
        self.assertNotIn("statefulsets", " ".join(paths))
        audit.assert_called_once_with("RunbookActionAllowed", "restart_diagnostic_probe", "allowed")

    def test_bad_arguments_are_iserror_results_not_protocol_errors(self):
        server = gateway.ThreadingHTTPServer(("127.0.0.1", 0), gateway.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def call(params):
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}).encode()
            req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/mcp", data=body,
                                         headers={"Content-Type": "application/json"})
            return json.load(urllib.request.urlopen(req, timeout=5))

        bad = call({"name": "get_workload_status", "arguments": {"kind": "evil-kind-123", "namespace": "evil-ns-123"}})
        self.assertTrue(bad["result"]["isError"])
        value = json.loads(bad["result"]["content"][0]["text"])
        self.assertEqual((value["status"], value["reason"]), ("error", "invalid_arguments"))
        self.assertIn("namespace", value["message"])
        self.assertNotIn("evil", bad["result"]["content"][0]["text"])
        for params in ({"name": "nope"}, {"arguments": {}}, "x"):
            self.assertIn("error", call(params))
        with mock.patch.object(gateway, "kube_request", return_value={"items": []}):
            ok = call({"name": "get_workload_status", "arguments": {"kind": "pods", "namespace": "lnd-regtest"}})
        self.assertNotIn("isError", ok["result"])


if __name__ == "__main__":
    unittest.main()

    def test_runtime_failures_are_iserror_without_leaking_exception_text(self):
        server = gateway.ThreadingHTTPServer(("127.0.0.1", 0), gateway.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def call(params):
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}).encode()
            req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/mcp", data=body,
                                         headers={"Content-Type": "application/json"})
            return json.load(urllib.request.urlopen(req, timeout=5))

        boom = urllib.error.URLError("http://10.0.0.1:9090 LEAKMARKER")
        with mock.patch.object(gateway, "kube_request", side_effect=boom):
            down = call({"name": "get_workload_status", "arguments": {"kind": "pods", "namespace": "lnd-regtest"}})
            self.assertTrue(down["result"]["isError"])
            value = json.loads(down["result"]["content"][0]["text"])
            self.assertEqual(value["reason"], "tool_unavailable")
            self.assertEqual(value["message"], "get_workload_status could not reach its data source; treat as unknown, not healthy")
            self.assertNotIn("LEAKMARKER", json.dumps(down))
            self.assertIn("error", call({"name": "nope"}))
        with mock.patch.object(gateway, "kube_request", side_effect=[{"data": {"lastRestartEpoch": "0"}}, RuntimeError("LEAKMARKER")]), \
                mock.patch.object(gateway, "audit"):
            act = call({"name": "execute_allowlisted_response", "arguments": {"action": "restart_diagnostic_probe"}})
        self.assertTrue(act["result"]["isError"])
        text = act["result"]["content"][0]["text"]
        self.assertNotIn('"allowed"', text)
        self.assertNotIn("LEAKMARKER", text)
        self.assertEqual(json.loads(text)["reason"], "tool_unavailable")
        self.assertIn("not confirmed", text)
