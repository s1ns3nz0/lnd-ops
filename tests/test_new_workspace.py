"""First-host setup must distinguish missing infrastructure from unreadable state."""
import contextlib
import importlib.machinery
import io
import pathlib
import subprocess
import sys
import unittest
from unittest.mock import patch

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "ops"))
start = importlib.machinery.SourceFileLoader("new_workspace_start", str(REPO / "ops/start")).load_module()


class NewWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.selection = self.stack.enter_context(patch.object(start, "load_selection", return_value={"choice": "new-testnet"}))
        self.stack.enter_context(patch.object(start, "runtime_environment", return_value={"KUBECONFIG": str(start.STATE / "kubeconfig")}))
        self.execute = self.stack.enter_context(patch.object(start, "execute", return_value=0))
        self.query = self.stack.enter_context(patch.object(start, "kubectl_json", return_value={"items": []}))
        self.pin = self.stack.enter_context(patch.object(start, "select_wallet"))

    def test_fresh_host_builds_and_pins_pvc_before_phase_progress(self):
        with patch.object(start, "selection_gate", side_effect=["new", None]), \
                patch.object(start, "inspect", return_value=("complete", "ok")):
            self.assertEqual(start.build_through(2), 0)
        self.assertEqual([c.args[0] for c in self.execute.call_args_list],
                         [("ops/doctor",), ("ops/bootstrap",), ("ops/deploy", "testnet")])
        self.pin.assert_called_once_with("existing-testnet")

    def test_existing_resources_and_query_errors_block_deployment(self):
        for response in (None, {}, {"items": [{"metadata": {"name": "old"}}]}):
            with self.subTest(response=response):
                self.execute.reset_mock()
                self.query.return_value = response
                self.assertEqual(start.prepare_new_workspace(), 10)
                self.assertNotIn(("ops/deploy", "testnet"), [c.args[0] for c in self.execute.call_args_list])
                self.pin.assert_not_called()

    def test_running_workload_without_pvc_is_not_a_fresh_workspace(self):
        self.query.side_effect = [{"items": []}, {"items": [{"metadata": {"name": "lnd-0"}}]}]
        self.assertEqual(start.prepare_new_workspace(), 10)
        self.assertEqual(self.execute.call_count, 2)
        self.pin.assert_not_called()

    def test_bootstrap_failure_stops_before_deploy(self):
        self.execute.side_effect = [0, 1]
        self.assertEqual(start.prepare_new_workspace(), 1)
        self.query.assert_not_called()
        self.pin.assert_not_called()

    def test_failed_deployment_does_not_adopt_partial_resources(self):
        self.execute.side_effect = [0, 0, 1]
        self.assertEqual(start.prepare_new_workspace(), 1)
        self.pin.assert_not_called()

    def test_pinning_failure_prevents_phase_progress(self):
        self.pin.side_effect = RuntimeError("PVC missing")
        with patch.object(start, "selection_gate", return_value="new"), \
                patch.object(start, "inspect") as inspect:
            with self.assertRaisesRegex(RuntimeError, "PVC missing"):
                start.build_through(2)
        inspect.assert_not_called()

    def test_custom_cluster_is_not_bootstrapped(self):
        with patch.object(start, "runtime_environment", return_value={"KUBECONFIG": "/other/config"}):
            self.assertEqual(start.prepare_new_workspace(), 10)
        self.execute.assert_not_called()

    def test_existing_selection_does_not_provision(self):
        self.selection.return_value = {"choice": "existing-testnet"}
        self.assertEqual(start.prepare_new_workspace(), 0)
        self.execute.assert_not_called()

    def test_dry_run_does_not_provision_or_select(self):
        with patch.object(start, "guide_operator", return_value="complete"):
            start.build_through(2, dry_run=True)
        self.query.assert_not_called()
        self.pin.assert_not_called()
        self.assertTrue(all(c.args[1] is True for c in self.execute.call_args_list))

    def test_testnet_choice_at_phase_one_does_not_deploy_testnet(self):
        with patch.object(start, "selection_gate", return_value="new"):
            self.assertEqual(start.build_through(1), 10)
        self.execute.assert_not_called()

    def test_new_regtest_pins_both_wallets_via_existing_selection(self):
        self.selection.return_value = {"choice": "new-regtest"}
        self.assertEqual(start.prepare_new_workspace(), 0)
        self.pin.assert_called_once_with("existing-regtest")
        self.assertEqual(self.execute.call_args.args[0], ("ops/deploy", "regtest"))


class NewTestnetWalletTests(unittest.TestCase):
    def test_missing_wallet_requires_explicit_creation_and_can_be_skipped(self):
        with patch.object(start, "inspect", return_value=("partial", "unlock the persistent testnet wallet")), \
                patch.object(start, "regtest_wallet_state", return_value="NON_EXISTING"), \
                patch.object(start, "run_confirmed", return_value=False) as create, \
                patch.object(start, "run_testnet_unlock") as unlock, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(start.guide_testnet(2, start.PHASES[1]), "partial")
        self.assertEqual(create.call_args.args[1], ("ops/create-testnet-wallet",))
        unlock.assert_not_called()

    def test_unknown_wallet_state_never_attempts_create_or_unlock(self):
        with patch.object(start, "inspect", return_value=("partial", "unlock the persistent testnet wallet")), \
                patch.object(start, "regtest_wallet_state", return_value="UNKNOWN"), \
                patch.object(start, "run_confirmed") as create, \
                patch.object(start, "run_testnet_unlock") as unlock, \
                patch.object(start, "wait_for_phase", return_value=False), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(start.guide_testnet(2, start.PHASES[1]), "partial")
        create.assert_not_called()
        unlock.assert_not_called()


class FreshStorageChecks(unittest.TestCase):
    def test_query_failure_is_not_absence(self):
        with patch.object(start.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "forbidden")):
            with self.assertRaisesRegex(RuntimeError, "PVC 조회 실패"):
                start.wallet_pvc_snapshot(strict=True)

    def test_not_found_success_is_absence(self):
        with patch.object(start.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")):
            self.assertEqual(start.wallet_pvc_snapshot(strict=True), {})

    def test_claim_appearing_before_deploy_blocks_command(self):
        with patch.object(start, "wallet_pvc_snapshot", return_value={"lnd-testnet/data-lnd-0-0": "old"}), \
                patch.object(start.subprocess, "run") as run, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "workspace PVC"):
                start.execute(("ops/deploy", "testnet"), fresh_profile="testnet")
        run.assert_not_called()

    def test_failed_pre_or_post_snapshot_never_reports_success(self):
        for snapshots, runs in (([RuntimeError("unreadable")], 0), ([{}, RuntimeError("unreadable")], 1)):
            with self.subTest(runs=runs), patch.object(start, "wallet_pvc_snapshot", side_effect=snapshots), \
                    patch.object(start.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run, \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "unreadable"):
                    start.execute(("ops/deploy", "testnet"), fresh_profile="testnet")
                self.assertEqual(run.call_count, runs)


if __name__ == "__main__":
    unittest.main()
