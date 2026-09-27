import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ops"))
from router_vm import approve, ensure_started, inventory
from router_store import read, write


class VMTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        base = pathlib.Path(self.directory.name)
        self.root = base / "state"
        self.vm = base / "lnd-ops-k3s"
        self.vm.mkdir()
        (self.vm / "lima.yaml").write_text("vmType: vz\n")
        self.item = {"name": "lnd-ops-k3s", "dir": str(self.vm), "status": "Stopped"}
        self.inventory = patch("router_vm.inventory", side_effect=lambda *args: dict(self.item)).start()
        self.addCleanup(patch.stopall)
        patch("router_vm.time.monotonic", return_value=0).start()
        approve(self.root, "/tools/limactl", "lnd-ops-k3s")

    def test_start_uses_only_existing_name_and_requires_later_running_observation(self):
        with patch("router_vm.subprocess.run", return_value=Mock(returncode=0)) as run:
            self.assertFalse(ensure_started(self.root, now=100))
            self.assertEqual(run.call_args.args[0], ["/tools/limactl", "start", "--tty=false", "--timeout=2m", "lnd-ops-k3s"])
            self.assertFalse(ensure_started(self.root, now=101))
            self.assertEqual(run.call_count, 1)
            self.item["status"] = "Running"
            self.assertTrue(ensure_started(self.root, now=102))
            self.assertEqual(run.call_count, 1)

    def test_three_failed_attempts_remain_exhausted_across_calls(self):
        with patch("router_vm.subprocess.run", return_value=Mock(returncode=1)) as run:
            for now in (100, 101, 130, 150, 190, 1000, 2000):
                self.assertFalse(ensure_started(self.root, now=now))
            self.assertEqual(run.call_count, 3)
        self.assertEqual(read(self.root, "vm-start.json")["state"], "needs_review")

    def test_timeout_is_uncertain_and_never_resets_budget(self):
        with patch("router_vm.subprocess.run", side_effect=subprocess.TimeoutExpired("limactl", 130)):
            self.assertFalse(ensure_started(self.root, now=100))
        saved = read(self.root, "vm-start.json")
        self.assertEqual(saved["state"], "uncertain")
        self.assertEqual(saved["attempts"], 1)
        self.item["status"] = "Running"
        self.assertTrue(ensure_started(self.root, now=240))

    def test_changed_vm_configuration_blocks_start(self):
        (self.vm / "lima.yaml").write_text("vmType: qemu\n")
        with patch("router_vm.subprocess.run") as run, self.assertRaisesRegex(ValueError, "바뀌었습니다"):
            ensure_started(self.root, now=100)
        run.assert_not_called()

    def test_backoff_begins_after_slow_failed_start(self):
        with patch("router_vm.time.monotonic", side_effect=[0, 130]), patch(
                "router_vm.subprocess.run", return_value=Mock(returncode=1)):
            self.assertFalse(ensure_started(self.root, now=100))
        self.assertEqual(read(self.root, "vm-start.json")["next_attempt_at"], 260)
        with patch("router_vm.subprocess.run") as run:
            self.assertFalse(ensure_started(self.root, now=259))
        run.assert_not_called()

    def test_interrupted_start_keeps_uncertain_attempt_and_budget(self):
        with patch("router_vm.subprocess.run", side_effect=SystemExit(0)), self.assertRaises(SystemExit):
            ensure_started(self.root, now=100)
        saved = read(self.root, "vm-start.json")
        self.assertEqual((saved["state"], saved["attempts"]), ("uncertain", 1))
        with patch("router_vm.subprocess.run") as run:
            self.assertFalse(ensure_started(self.root, now=101))
        run.assert_not_called()

    def test_malformed_approval_never_invokes_lima(self):
        original = read(self.root, "vm-start.json")
        records = [[], {**original, "attempts": -1}, {**original, "attempts": True},
                   {**original, "next_attempt_at": float("nan")}, {**original, "name": []}]
        for record in records:
            with self.subTest(record=record):
                write(self.root, "vm-start.json", record)
                self.inventory.reset_mock()
                with self.assertRaises(ValueError):
                    ensure_started(self.root, now=100)
                self.inventory.assert_not_called()

    def test_symlink_approval_and_lock_are_rejected(self):
        for name in ("vm-start.json", "vm-start.lock"):
            with self.subTest(name=name):
                path = self.root / name
                saved = path.read_bytes()
                path.unlink()
                path.symlink_to(self.vm / "lima.yaml")
                with patch("router_vm.subprocess.run") as run, self.assertRaises(OSError):
                    ensure_started(self.root, now=100)
                run.assert_not_called()
                path.unlink()
                path.write_bytes(saved)
                path.chmod(0o600)

    def test_transitional_vm_does_not_get_another_start(self):
        self.item["status"] = "Starting"
        with patch("router_vm.subprocess.run") as run:
            self.assertFalse(ensure_started(self.root, now=100))
        run.assert_not_called()
        self.assertEqual(read(self.root, "vm-start.json")["attempts"], 0)


class InventoryTests(unittest.TestCase):
    def test_missing_vm_is_not_created(self):
        with patch("router_vm.subprocess.run", return_value=Mock(stdout="", returncode=0)) as run, self.assertRaises(ValueError):
            inventory("/tools/limactl", "missing")
        self.assertEqual(run.call_args.args[0], ["/tools/limactl", "list", "missing", "--json"])

    def test_template_url_or_option_is_not_a_vm_name(self):
        for name in ("template:default", "https://vm", "../other", "--name=other"):
            with self.assertRaises(ValueError):
                inventory("/tools/limactl", name)


if __name__ == "__main__":
    unittest.main()
