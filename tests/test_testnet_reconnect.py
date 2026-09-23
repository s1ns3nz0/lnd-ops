import importlib.machinery
import importlib.util
import json
import pathlib
import stat
import tempfile
import unittest
import unittest.mock


REPO = pathlib.Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("testnet_reconnect", str(REPO / "ops/testnet-reconnect-check"))
spec = importlib.util.spec_from_loader(loader.name, loader)
reconnect = importlib.util.module_from_spec(spec)
loader.exec_module(reconnect)


class TestnetReconnectTests(unittest.TestCase):
    @staticmethod
    def state(pod_uid="pod-before"):
        return {
            "node_key": "02node", "pod_uid": pod_uid,
            "channel_points": ["tx:0"], "peer_pubkeys": ["03peer"],
        }

    def test_requires_explicit_mode(self):
        self.assertEqual(reconnect.main([]), 2)

    def test_prepare_writes_private_baseline(self):
        with tempfile.TemporaryDirectory() as directory, unittest.mock.patch.object(
            reconnect, "PENDING", pathlib.Path(directory) / "evidence/pending.json"
        ), unittest.mock.patch.object(reconnect, "snapshot", return_value=self.state()):
            self.assertEqual(reconnect.main(["prepare"]), 0)
            data = json.loads(reconnect.PENDING.read_text())
            self.assertEqual(data["before"]["pod_uid"], "pod-before")
            self.assertEqual(stat.S_IMODE(reconnect.PENDING.stat().st_mode), 0o600)

    def test_verify_requires_changed_pod_and_preserved_channel_peer(self):
        with tempfile.TemporaryDirectory() as directory:
            pending = pathlib.Path(directory) / "evidence/pending.json"
            with unittest.mock.patch.object(reconnect, "PENDING", pending), unittest.mock.patch.object(
                reconnect, "snapshot", side_effect=[self.state(), self.state("pod-after")]
            ):
                self.assertEqual(reconnect.main(["prepare"]), 0)
                self.assertEqual(reconnect.main(["verify"]), 0)
            self.assertFalse(pending.exists())
            evidence = list(pending.parent.glob("testnet-reconnect-*.json"))
            self.assertEqual(len(evidence), 1)
            self.assertEqual(json.loads(evidence[0].read_text())["result"], "pass")

    def test_verify_rejects_unchanged_pod(self):
        with tempfile.TemporaryDirectory() as directory:
            pending = pathlib.Path(directory) / "evidence/pending.json"
            with unittest.mock.patch.object(reconnect, "PENDING", pending), unittest.mock.patch.object(
                reconnect, "snapshot", return_value=self.state()
            ):
                self.assertEqual(reconnect.main(["prepare"]), 0)
                self.assertEqual(reconnect.main(["verify"]), 10)


if __name__ == "__main__":
    unittest.main()
