import contextlib
import importlib.machinery
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "ops"))
start = importlib.machinery.SourceFileLoader("router_support_start", str(REPO / "ops/start")).load_module()


class SupportMenuTests(unittest.TestCase):
    def test_host_recovery_gap_opens_recovery_menu_without_rebuilding(self):
        with patch.object(start, 'inspect', side_effect=[('pending', 'ACTION: Router 운영 증거가 미완료입니다.'), ('pending', 'still missing')]), \
                patch.object(start, 'router_recovery_menu') as menu, \
                patch.object(start.subprocess, 'run') as command, \
                patch.object(start, 'run_confirmed') as action, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(start.guide_evidence_phase(10, start.PHASES[9]), 'partial')
        menu.assert_called_once()
        action.assert_not_called()
        self.assertTrue(command.call_args.args[0][0].endswith('/ops/router-report'))

    def test_recovery_menu_only_captures_verifies_or_cancels_records(self):
        with patch("builtins.input", side_effect=["1", "2", "3", "0"]), \
                patch.object(start, "run_confirmed") as run, contextlib.redirect_stdout(io.StringIO()):
            start.router_recovery_menu()
        self.assertEqual([call.args[1] for call in run.call_args_list], [
            ("ops/router-host-recovery", action) for action in ("prepare", "verify", "cancel")])

    def test_wsl_login_registration_requires_separate_selection(self):
        for answer, count in (("", 1), ("y", 2)):
            with patch.object(start.platform, "system", return_value="Linux"), \
                    patch.object(start.platform, "release", return_value="microsoft-standard-WSL2"), \
                    patch("builtins.input", return_value=answer), patch.object(start, "run_confirmed", return_value=True) as run, \
                    contextlib.redirect_stdout(io.StringIO()):
                start.configure_router_service()
            self.assertEqual(run.call_count, count)
            if count == 2:
                self.assertEqual(run.call_args.args[1][0], "ops/windows-router-startup")

    def test_mac_vm_start_requires_explicit_selection(self):
        for answer, enabled in (("", False), ("y", True)):
            with patch.object(start.platform, "system", return_value="Darwin"), \
                    patch("builtins.input", return_value=answer), patch.object(start, "run_confirmed") as run, \
                    contextlib.redirect_stdout(io.StringIO()):
                start.configure_router_service()
            self.assertEqual("--start-vm" in run.call_args.args[1], enabled)

    def test_later_phase_does_not_require_optional_loop(self):
        with patch.object(start, "selection_gate", return_value=None), \
                patch.object(start, "inspect", return_value=("complete", "verified")) as inspect, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(start.build_through(5), 0)
        self.assertEqual([call.args[0] for call in inspect.call_args_list], [0, 1, 2, 4])

    def test_explicit_loop_selection_still_checks_loop(self):
        with patch.object(start, "selection_gate", return_value=None), \
                patch.object(start, "inspect", return_value=("complete", "verified")) as inspect, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(start.build_through(4), 0)
        self.assertEqual([call.args[0] for call in inspect.call_args_list], [0, 1, 2, 3])

    def test_support_actions_never_advance_or_verify_router_completion(self):
        with patch("builtins.input", side_effect=["1", "2", "3", "4", "5", "0"]), \
                patch.object(start, "run_confirmed", return_value=True) as run, \
                patch.object(start, "build_through") as advance, contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(start.router_support_menu())
        advance.assert_not_called()
        commands = [call.args[1] for call in run.call_args_list]
        self.assertEqual(commands, [("ops/deploy-monitoring",), ("ops/deploy", "testnet", "--monitoring"),
                                    ("ops/verify-monitoring", "--profile", "testnet"),
                                    ("ops/backup-scb-encrypted", "testnet", "lnd-0"),
                                    ("ops/backup-status-encrypted", "testnet", "lnd-0")])

    def test_invalid_selection_and_cancellation_make_no_changes(self):
        with patch("builtins.input", side_effect=["bad", "0"]), patch.object(start, "run_confirmed") as run, \
                contextlib.redirect_stdout(io.StringIO()):
            start.router_support_menu()
        run.assert_not_called()

    def test_interrupted_support_action_returns_without_advancing(self):
        with patch("builtins.input", return_value="4"), patch.object(start, "run_confirmed", side_effect=KeyboardInterrupt), \
                patch.object(start, "build_through") as advance, contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(start.router_support_menu())
        advance.assert_not_called()

    def test_historical_proof_has_timestamp_but_error_does_not_claim_current_readiness(self):
        snapshot = {"code": "query_error", "ready": True, "forwarding_proof": "verified", "proof_verified_at": 1000}
        with patch.object(start, "render_router_lines", side_effect=lambda rows, previous: rows):
            rows = start.render_router_snapshot(snapshot, None, None, 0, None)
        self.assertIn("조회 실패", rows[3])
        self.assertIn("실경유 이력 확인", rows[4])
        self.assertIn("외부 접속  미검증", rows[5])


class MonitoringRedeployTests(unittest.TestCase):
    def execute(self, count=3, locked=""):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            kubeconfig = root / "kubeconfig"
            kubeconfig.touch()
            logger = '''#!/usr/bin/env python3
import json,os,pathlib,sys
args=sys.argv[1:]
with open(os.environ["LND_TEST_LOG"],"a") as out: out.write(json.dumps([pathlib.Path(sys.argv[0]).name,*args])+"\\n")
if pathlib.Path(sys.argv[0]).name=="helm" and "get" in args: print(os.environ["LND_TEST_VALUES"])
if pathlib.Path(sys.argv[0]).name=="kubectl" and "getinfo" in args and os.environ.get("LND_TEST_LOCKED") in args: sys.exit(1)
'''
            for name in ("helm", "kubectl"):
                path = root / name
                path.write_text(logger)
                path.chmod(0o700)
            log = root / "commands.jsonl"
            values = {"lnd": {"nodes": count}, "router": {"enabled": True, "externalIP": "router.example"}}
            env = os.environ | {"PATH": str(root) + os.pathsep + os.environ["PATH"], "KUBECONFIG": str(kubeconfig),
                                "LND_TEST_LOG": str(log), "LND_TEST_VALUES": json.dumps(values), "LND_TEST_LOCKED": locked}
            result = subprocess.run([str(REPO / "ops/deploy"), "testnet", "--monitoring"], env=env, capture_output=True, text=True, timeout=20)
            return result, [json.loads(line) for line in log.read_text().splitlines()]

    def test_monitoring_preserves_existing_node_count_and_router_endpoint(self):
        result, commands = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        upgrade = next(args for args in commands if args[0] == "helm" and "upgrade" in args)
        self.assertIn("lnd.nodes=3", upgrade)
        self.assertIn("router.enabled=true", upgrade)
        self.assertIn("router.externalIP=router.example", upgrade)
        checked = [args for args in commands if args[0] == "kubectl" and "getinfo" in args]
        self.assertEqual(len(checked), 3)

    def test_locked_additional_wallet_blocks_redeploy_before_mutation(self):
        result, commands = self.execute(locked="lnd-2-0")
        self.assertEqual(result.returncode, 10)
        self.assertFalse(any("upgrade" in args for args in commands))

    def test_invalid_saved_node_count_never_defaults_to_one(self):
        result, commands = self.execute(count=0)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(any("upgrade" in args for args in commands))


if __name__ == "__main__":
    unittest.main()
