import importlib.machinery
import importlib.util
import json
import pathlib
import stat
import tempfile
import unittest
import unittest.mock


REPO = pathlib.Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("testnet_acceptance", str(REPO / "ops/testnet-acceptance"))
spec = importlib.util.spec_from_loader(loader.name, loader)
acceptance = importlib.util.module_from_spec(spec)
loader.exec_module(acceptance)


class TestnetAcceptanceTests(unittest.TestCase):
    @staticmethod
    def current():
        return {
            "node_key": "02node", "external_peer_pubkeys": ["03peer"], "channel_points": ["tx:0"],
            "active_public_channel_points": ["tx:0"],
            "lnd_pvc_uid": "lnd-pvc", "prometheus_pvc_uid": "prom-pvc", "scb_source_sha256": "a" * 64,
            "cluster_uid_sha256": "b" * 64, "helm_revisions": {"lnd-ops": 4, "lnd-ops-monitoring": 5},
            "recent_outgoing_count": 1, "recent_incoming_count": 1,
        }

    @classmethod
    def redeploy(cls):
        preserved = {
            "node_key": "02node", "channel_points": ["tx:0"], "lnd_pvc_uid": "lnd-pvc",
            "prometheus_pvc_uid": "prom-pvc", "scb_source_sha256": "a" * 64,
            "scb_host_sha256": "c" * 64, "scb_plaintext_sha256": "a" * 64, "scb_format": "gpg-symmetric-v1",
            "cluster_uid_sha256": "b" * 64, "prometheus_series_sha256": "d" * 64,
            "prometheus_sample": [1700000000.0, "1"],
        }
        return {
            "schema": "lnd-ops/redeploy-evidence/v1", "result": "pass", "profile": "testnet",
            "finished_at": "2023-11-14T22:14:00Z",
            "before": dict(preserved, helm_revisions={"lnd-ops": 3, "lnd-ops-monitoring": 4}),
            "after": dict(preserved, helm_revisions={"lnd-ops": 4, "lnd-ops-monitoring": 5}),
        }

    def write_redeploy(self, root, content=None):
        root.mkdir(parents=True, exist_ok=True)
        path = root / "testnet-redeploy-proof.json"
        path.write_text(json.dumps(content or self.redeploy()))
        path.chmod(0o600)
        return path

    def test_complete_pass_writes_private_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = pathlib.Path(directory) / "evidence"
            self.write_redeploy(evidence)
            with unittest.mock.patch.object(acceptance, "EVIDENCE", evidence), unittest.mock.patch.object(
                acceptance, "command"
            ), unittest.mock.patch.object(acceptance, "live_state", return_value=self.current()), unittest.mock.patch.object(
                acceptance, "verify_prometheus_history"
            ):
                path, payload = acceptance.acceptance(now=1700000100.0)
            self.assertEqual(payload["schema"], "lnd-ops/testnet-acceptance/v1")
            self.assertEqual(set(payload["checks"].values()), {"pass"})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_stale_redeploy_is_manual_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = pathlib.Path(directory)
            self.write_redeploy(evidence)
            with unittest.mock.patch.object(acceptance, "EVIDENCE", evidence):
                with self.assertRaisesRegex(acceptance.ManualGate, "older than 24 hours"):
                    acceptance.latest_redeploy(1700100000.0)

    def test_current_identity_mismatch_fails(self):
        current = self.current()
        current["node_key"] = "different"
        with unittest.mock.patch.object(acceptance, "verify_prometheus_history"):
            with self.assertRaisesRegex(acceptance.InvariantFailure, "node_key"):
                acceptance.verify_matches(current, self.redeploy())

    def test_live_state_preserves_public_and_private_channel_points(self):
        replies = {
            "getinfo": {"identity_pubkey": "02node", "synced_to_chain": True},
            "listpeers": {"peers": [{"pub_key": "03" + "a" * 64}]},
            "listchannels": {"channels": [
                {"channel_point": "public:0", "remote_pubkey": "03" + "a" * 64, "active": True,
                 "private": False, "capacity": "100000"},
                {"channel_point": "payer:1", "remote_pubkey": "03" + "b" * 64, "active": False,
                 "private": True, "capacity": "30000"},
            ]},
            "listpayments": {"payments": [{"status": "SUCCEEDED", "creation_date": "1700000000"}]},
            "listinvoices": {"invoices": [{"state": "SETTLED", "settle_date": "1700000000"}]},
        }

        def lncli(operation, *_args):
            return replies[operation]

        objects = iter([
            {"metadata": {"uid": "lnd-pvc"}},
            {"metadata": {"uid": "prom-pvc"}},
            {"metadata": {"uid": "cluster"}},
        ])
        history = json.dumps([{"revision": 4}])
        with unittest.mock.patch.object(acceptance, "lncli", side_effect=lncli), unittest.mock.patch.object(
            acceptance, "kubectl_json", side_effect=lambda *_args: next(objects)
        ), unittest.mock.patch.object(
            acceptance, "kubectl", return_value="a" * 64 + "  channel.backup\n"
        ), unittest.mock.patch.object(acceptance, "command", return_value=history):
            state = acceptance.live_state(1700000100)

        self.assertEqual(state["channel_points"], ["payer:1", "public:0"])
        self.assertEqual(state["active_public_channel_points"], ["public:0"])


if __name__ == "__main__":
    unittest.main()
