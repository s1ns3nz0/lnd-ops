import pathlib
import os
import subprocess
import runpy
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ops"))
from router_monitor import Observations, status
from router_store import operation_lock, read


def result(code, ready=False):
    return {"code": code, "ready": ready, "checked_at": 123, "message": code}


class MonitorTests(unittest.TestCase):
    def test_live_heartbeat_does_not_make_old_or_failed_observation_ready(self):
        record = {'schema': 'lnd-ops/router-monitor/v1', 'running': True, 'heartbeat_at': 200,
                  'current': result('complete', True) | {'checked_at': 190,
                      'external_reachability': 'operator_attested', 'external_expires_at': 300}}
        self.assertTrue(status(record, 200)['ready'])
        self.assertEqual(status(record, 200)['external_reachability'], 'operator_attested')
        self.assertFalse(status(record | {'heartbeat_at': 100}, 200)['ready'])
        self.assertFalse(status(record | {'running': False}, 200)['ready'])
        for stamp in (100, 201, float('nan'), True, None):
            with self.subTest(stamp=stamp):
                value = status(record | {'current': record['current'] | {'checked_at': stamp}}, 200)
                self.assertFalse(value['ready'])
                self.assertTrue(value['monitor_alive'])
        value = status(record | {'current': record['current'] | {'code': 'query_error'}}, 200)
        self.assertFalse(value['ready'])

    def test_external_expiry_is_not_an_operational_outage(self):
        record = {'schema': 'lnd-ops/router-monitor/v1', 'running': True, 'heartbeat_at': 200,
                  'current': result('external_required', True) | {'checked_at': 195,
                      'external_reachability': 'operator_attested', 'external_expires_at': 200}}
        value = status(record, 200)
        self.assertTrue(value['ready'])
        self.assertEqual(value['external_reachability'], 'unverified')
        self.assertFalse(status(None, 200)['ready'])

    def test_stalled_probe_has_separate_sustained_alert_and_resumption(self):
        state = Observations(threshold=120)
        state.accept(result('complete', True) | {'checked_at': 100}, 0)
        self.assertEqual(state.check_freshness(0, 100), [])
        self.assertEqual(state.check_freshness(31, 131), [{'event': 'observation_stale'}])
        self.assertEqual(state.check_freshness(150, 250), [])
        self.assertEqual(state.check_freshness(151, 251)[0]['event'], 'observation_alert')
        self.assertEqual(state.check_freshness(160, 260), [])
        state.accept(result('wallet_locked') | {'checked_at': 261}, 161)
        events = state.check_freshness(161, 261)
        self.assertEqual(events, [{'event': 'observation_resumed', 'code': 'wallet_locked'}])
        self.assertFalse(state.stale_alerted)
        self.assertEqual(state.condition, 'wallet_locked')

    def test_status_command_does_not_start_daemon_or_contact_cluster(self):
        entry = runpy.run_path(str(pathlib.Path(__file__).resolve().parents[1] / 'ops/router-monitor'))['main']
        import contextlib
        import io
        with patch.dict(entry.__globals__, read=Mock(return_value=None), StatusWorker=Mock()) as scope, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(entry(['--status', '--json']), 0)
            scope['StatusWorker'].assert_not_called()
        self.assertIn('"state": "missing"', output.getvalue())

    def test_probe_reconnects_approved_peers_only_after_identity_and_sync_check(self):
        probe = runpy.run_path(str(pathlib.Path(__file__).resolve().parents[1] / "ops/router-monitor"))["probe"]
        reconnect = Mock(return_value=[])
        for status in (
            {"code": "wallet_locked"},
            {"code": "wrong_network", "identity": "other", "synced_to_chain": True},
            {"code": "syncing", "identity": "self", "synced_to_chain": False},
            {"code": "query_error", "identity": "self", "synced_to_chain": True},
        ):
            with patch.dict(probe.__globals__, reconnect=reconnect), patch("runpy.run_path", return_value={"snapshot": lambda: status}):
                probe()
        reconnect.assert_not_called()
        with patch.dict(probe.__globals__, reconnect=reconnect), patch("runpy.run_path", return_value={"snapshot": lambda: {
            "code": "proof_required", "identity": "self", "synced_to_chain": True, "ready": True}}):
            probe()
        reconnect.assert_called_once()

    def test_daemon_excludes_duplicate_and_records_graceful_shutdown(self):
        repo = pathlib.Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            binary = root / "bin"
            binary.mkdir()
            kubectl = binary / "kubectl"
            kubectl.write_text("#!/bin/sh\nexit 0\n")
            kubectl.chmod(0o700)
            env = os.environ | {"XDG_STATE_HOME": str(root / "state"), "PATH": str(binary) + os.pathsep + os.environ["PATH"]}
            command = [sys.executable, str(repo / "ops/router-monitor")]
            process = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            store = root / "state/lnd-ops/router"
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    saved = read(store, "monitor.json")
                    if saved and saved.get("current"):
                        break
                    if process.poll() is not None:
                        self.fail(process.stderr.read())
                    time.sleep(.05)
                else:
                    self.fail("monitor never persisted its completed observation")
                self.assertEqual(saved["current"]["code"], "exposure_required")
                duplicate = subprocess.run(command, env=env, capture_output=True, text=True, timeout=5)
                self.assertEqual(duplicate.returncode, 1)
                process.terminate()
                _, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertFalse(read(store, "monitor.json")["running"])
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)

    def test_sustained_fault_alerts_once_and_ready_recovers_without_traffic(self):
        state = Observations(threshold=120)
        self.assertEqual(state.accept(result("peer_disconnected"), 0)[0]["event"], "status")
        self.assertEqual(state.accept(result("peer_disconnected"), 119), [])
        self.assertEqual(state.accept(result("peer_disconnected"), 120)[0]["event"], "alert")
        self.assertEqual(state.accept(result("peer_disconnected"), 240), [])
        self.assertEqual(state.accept(result("proof_required", True), 241)[-1]["event"], "recovered")
        self.assertEqual(state.accept(result("proof_required", True), 9999), [])

    def test_new_fault_does_not_claim_recovery(self):
        state = Observations(threshold=0)
        state.accept(result("wallet_locked"), 0)
        events = state.accept(result("query_error"), 1)
        self.assertNotIn("recovered", [event["event"] for event in events])
        self.assertEqual(state.last_good["code"], "wallet_locked")

    def test_restart_does_not_count_unobserved_downtime_as_sustained_fault(self):
        state = Observations(threshold=120)
        self.assertEqual(len(state.accept(result("syncing"), 99999)), 1)
        self.assertFalse(state.alerted)

    def test_monitor_lock_excludes_second_monitor_without_blocking_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            with operation_lock(root, "monitor.lock"):
                with self.assertRaises(BlockingIOError):
                    with operation_lock(root, "monitor.lock"):
                        self.fail("second monitor acquired lock")
                with operation_lock(root):
                    pass

    def test_persisted_error_keeps_last_observation_separate_and_marks_shutdown(self):
        state = Observations()
        state.accept(result("proof_required", True), 0)
        state.accept(result("query_error"), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            state.save(root, running=False)
            saved = read(root, "monitor.json")
            self.assertFalse(saved["running"])
            self.assertFalse(saved["probe_in_progress"])
            self.assertIsNotNone(saved["observation_received_at"])
            self.assertEqual(saved["current"]["code"], "query_error")
            self.assertTrue(saved["last_successful"]["ready"])


if __name__ == "__main__":
    unittest.main()
