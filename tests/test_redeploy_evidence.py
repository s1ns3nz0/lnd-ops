import importlib.machinery
import importlib.util
import json
import pathlib
import stat
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timezone


REPO = pathlib.Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("redeploy_check", str(REPO / "ops/redeploy-check"))
spec = importlib.util.spec_from_loader(loader.name, loader)
redeploy = importlib.util.module_from_spec(spec)
loader.exec_module(redeploy)


class RedeployEvidenceTests(unittest.TestCase):
    @staticmethod
    def snapshot(lnd_revision=1, monitoring_revision=1):
        return {
            "node_key": "02public",
            "channel_points": ["txid:0"],
            "lnd_pvc_uid": "lnd-pvc",
            "prometheus_pvc_uid": "prom-pvc",
            "scb_source_sha256": "a" * 64,
            "scb_host_sha256": "a" * 64,
            "cluster_uid": "cluster-uid",
            "helm_revisions": {
                "lnd-ops": lnd_revision,
                "lnd-ops-monitoring": monitoring_revision,
            },
            "prometheus_sample": [1700000000.0, "1"],
            "prometheus_series": {
                "__name__": "up",
                "job": "node-exporter",
                "instance": "private-host:9100",
            },
        }

    def test_writes_private_secret_free_evidence(self):
        snapshot = self.snapshot(1, 2)
        with tempfile.TemporaryDirectory() as directory, unittest.mock.patch.dict(
            redeploy.os.environ, {"XDG_STATE_HOME": directory}
        ):
            path = pathlib.Path(directory) / "lnd-ops/evidence/proof.json"
            now = datetime(2026, 9, 23, 1, 2, 3, tzinfo=timezone.utc)
            finished = datetime(2026, 9, 23, 1, 3, 4, tzinfo=timezone.utc)
            redeploy.write_evidence(path, snapshot, snapshot, now, finished)
            data = json.loads(path.read_text())
            self.assertEqual(data["result"], "pass")
            self.assertEqual(data["started_at"], "2026-09-23T01:02:03Z")
            self.assertEqual(data["finished_at"], "2026-09-23T01:03:04Z")
            self.assertEqual(data["before"], data["after"])
            self.assertNotIn("private-host", path.read_text())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_custom_evidence_argument(self):
        with tempfile.TemporaryDirectory() as directory, unittest.mock.patch.dict(
            redeploy.os.environ, {"XDG_STATE_HOME": directory}
        ):
            path = redeploy.parse_args(["--evidence", "proof.json"])
            self.assertEqual(path, (pathlib.Path(directory) / "lnd-ops/evidence/proof.json").resolve())
            with self.assertRaises(ValueError):
                redeploy.parse_args(["--evidence", "/tmp/outside.json"])
            with self.assertRaises(ValueError):
                redeploy.parse_args(["unexpected"])

    def test_success_path_redeploys_both_releases_and_writes_evidence(self):
        before = self.snapshot(3, 7)
        after = self.snapshot(4, 8)
        with tempfile.TemporaryDirectory() as directory, unittest.mock.patch.dict(
            redeploy.os.environ, {"XDG_STATE_HOME": directory}
        ), unittest.mock.patch.object(
            redeploy, "host_scb_path", return_value=pathlib.Path("/host/channel.backup")
        ), unittest.mock.patch.object(
            redeploy, "snapshot", side_effect=[before, after]
        ) as snapshot_mock, unittest.mock.patch.object(
            redeploy.subprocess, "run"
        ) as run_mock, unittest.mock.patch.object(
            redeploy, "write_evidence"
        ) as evidence_mock:
            result = redeploy.main(["--evidence", "success.json"])

        self.assertEqual(result, 0)
        self.assertEqual(snapshot_mock.call_count, 2)
        snapshot_mock.assert_any_call(pathlib.Path("/host/channel.backup"))
        snapshot_mock.assert_any_call(
            pathlib.Path("/host/channel.backup"), 1700000000.0, before["prometheus_series"]
        )
        self.assertEqual(
            [call.args[0] for call in run_mock.call_args_list],
            [
                [str(redeploy.repo / "ops/deploy"), "testnet"],
                [str(redeploy.repo / "ops/deploy-monitoring")],
            ],
        )
        evidence_mock.assert_called_once()
        self.assertEqual(evidence_mock.call_args.args[1:3], (before, after))

    def test_does_not_write_pass_evidence_without_helm_revision_change(self):
        before = self.snapshot(3, 7)
        after = self.snapshot(3, 8)
        with tempfile.TemporaryDirectory() as directory, unittest.mock.patch.dict(
            redeploy.os.environ, {"XDG_STATE_HOME": directory}
        ), unittest.mock.patch.object(
            redeploy, "host_scb_path", return_value=pathlib.Path("/host/channel.backup")
        ), unittest.mock.patch.object(
            redeploy, "snapshot", side_effect=[before, after]
        ), unittest.mock.patch.object(
            redeploy.subprocess, "run"
        ), unittest.mock.patch.object(
            redeploy, "write_evidence"
        ) as evidence_mock:
            result = redeploy.main(["--evidence", "failure.json"])

        self.assertEqual(result, 1)
        evidence_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
