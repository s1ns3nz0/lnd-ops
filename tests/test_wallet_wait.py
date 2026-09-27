import contextlib
import io
import json
import pathlib
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ops"))
import wallet_wait


class WalletWaitTests(unittest.TestCase):
    def wait(self, rpc, ready=None, timeout=6):
        now = [0]
        def sleep(seconds):
            now[0] += seconds
        return wallet_wait.wait_for_state(timeout=timeout, rpc=rpc,
            clock=lambda: now[0], sleep=sleep, container_ready=ready or Mock(return_value=True))

    def test_restart_error_then_locked(self):
        rpc = Mock(side_effect=[RuntimeError('container not found ("lnd")'), {"state": "LOCKED"}])
        self.assertEqual(self.wait(rpc), "LOCKED")
        self.assertEqual(rpc.call_count, 2)

    def test_old_revision_never_queried_for_wallet_state(self):
        ready = Mock(side_effect=[False, False, True])
        rpc = Mock(return_value={"state": "LOCKED"})
        self.assertEqual(self.wait(rpc, ready), "LOCKED")
        rpc.assert_called_once()

    def test_empty_output_and_startup_states_are_retried(self):
        rpc = Mock(side_effect=[json.JSONDecodeError("empty", "", 0), {"state": "RPC_ACTIVE"}, {"state": "SERVER_ACTIVE"}])
        self.assertEqual(self.wait(rpc), "SERVER_ACTIVE")

    def test_non_existing_wallet_is_returned_without_creation(self):
        rpc = Mock(return_value={"state": "NON_EXISTING"})
        self.assertEqual(self.wait(rpc), "NON_EXISTING")
        self.assertEqual(rpc.call_args.args, ("state",))

    def test_permanent_error_has_bounded_wait(self):
        rpc = Mock(side_effect=RuntimeError("unavailable"))
        with self.assertRaisesRegex(RuntimeError, "대기 시간이.*unavailable"):
            self.wait(rpc)
        self.assertEqual(rpc.call_count, 3)

    def test_main_reports_timeout_without_traceback(self):
        error = io.StringIO()
        with patch.object(wallet_wait, "wait_for_state", side_effect=RuntimeError("timeout")), \
                contextlib.redirect_stderr(error):
            self.assertEqual(wallet_wait.main(), 10)
        self.assertEqual(error.getvalue(), "보류: timeout\n")


class ContainerRevisionTests(unittest.TestCase):
    def setUp(self):
        self.workload = {"metadata": {"generation": 2}, "status": {"observedGeneration": 2, "updateRevision": "new"}}
        self.pod = {"metadata": {"labels": {"controller-revision-hash": "new"}}, "status": {
            "containerStatuses": [{"name": "lnd", "state": {"running": {}}},
                                  {"name": "lndmon", "state": {"waiting": {"reason": "CrashLoopBackOff"}}}]}}

    def ready(self):
        run = Mock(side_effect=[subprocess.CompletedProcess([], 0, json.dumps(value), "") for value in (self.workload, self.pod)])
        return wallet_wait.current_container(10, clock=lambda: 0, run=run)

    def test_wallet_locked_sidecar_does_not_block_unlock(self):
        self.assertTrue(self.ready())

    def test_controller_must_observe_latest_generation(self):
        self.workload["status"]["observedGeneration"] = 1
        self.assertFalse(self.ready())

    def test_old_pod_is_not_ready(self):
        self.pod["metadata"]["labels"]["controller-revision-hash"] = "old"
        self.assertFalse(self.ready())

    def test_terminating_pod_is_not_ready(self):
        self.pod["metadata"]["deletionTimestamp"] = "now"
        self.assertFalse(self.ready())

    def test_missing_lnd_container_is_not_ready(self):
        self.pod["status"]["containerStatuses"] = []
        self.assertFalse(self.ready())

    def test_container_starting_is_not_ready(self):
        self.pod["status"]["containerStatuses"][0]["state"] = {"waiting": {}}
        self.assertFalse(self.ready())


if __name__ == "__main__":
    unittest.main()
