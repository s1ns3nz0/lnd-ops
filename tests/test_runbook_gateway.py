import importlib.util
import pathlib
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


if __name__ == "__main__":
    unittest.main()
