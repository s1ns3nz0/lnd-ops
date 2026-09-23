import importlib.machinery
import importlib.util
import json
import pathlib
import stat
import tempfile
import time
import unittest
import unittest.mock


REPO = pathlib.Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("regtest_acceptance", str(REPO / "ops/acceptance"))
spec = importlib.util.spec_from_loader(loader.name, loader)
acceptance = importlib.util.module_from_spec(spec)
loader.exec_module(acceptance)


class RegtestAcceptanceTests(unittest.TestCase):
    @staticmethod
    def nodes():
        return {
            "lnd-0": {
                "node_key": "02a",
                "channel_points": ["tx:0"],
                "lnd_pvc_uid": "pvc-0",
                "scb_source_sha256": "a" * 64,
                "recent_outgoing_count": 1,
                "recent_incoming_count": 1,
            },
            "lnd-1": {
                "node_key": "02b",
                "channel_points": ["tx:0"],
                "lnd_pvc_uid": "pvc-1",
                "scb_source_sha256": "b" * 64,
                "recent_outgoing_count": 1,
                "recent_incoming_count": 1,
            },
        }

    @classmethod
    def current(cls):
        return {
            "nodes": cls.nodes(),
            "prometheus_pvc_uid": "prom-pvc",
            "cluster_uid_sha256": "c" * 64,
            "helm_revisions": {"lnd-ops": 4, "lnd-ops-monitoring": 3},
        }

    @classmethod
    def redeploy(cls):
        nodes = {}
        for name, node in cls.nodes().items():
            nodes[name] = {key: value for key, value in node.items() if not key.startswith("recent_")}
            nodes[name]["scb_plaintext_sha256"] = node["scb_source_sha256"]
            nodes[name]["scb_host_sha256"] = ("d" if name == "lnd-0" else "e") * 64
        preserved = {
            "profile": "regtest",
            "nodes": nodes,
            "prometheus_pvc_uid": "prom-pvc",
            "cluster_uid_sha256": "c" * 64,
            "prometheus_series_sha256": "d" * 64,
            "prometheus_sample": [1700000000.0, "1"],
        }
        before = dict(preserved, helm_revisions={"lnd-ops": 3, "lnd-ops-monitoring": 2})
        after = dict(preserved, helm_revisions={"lnd-ops": 4, "lnd-ops-monitoring": 3})
        return {
            "schema": "lnd-ops/redeploy-evidence/v1",
            "result": "pass",
            "profile": "regtest",
            "finished_at": "2023-11-14T22:14:00Z",
            "before": before,
            "after": after,
        }

    def write_redeploy(self, root, content=None, name="regtest-redeploy-proof.json"):
        root.mkdir(parents=True, exist_ok=True)
        path = root / name
        path.write_text(json.dumps(content if content is not None else self.redeploy()))
        path.chmod(0o600)
        return path

    def test_complete_pass_writes_private_versioned_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = pathlib.Path(directory) / "evidence"
            self.write_redeploy(evidence)
            with unittest.mock.patch.object(acceptance, "EVIDENCE", evidence), unittest.mock.patch.object(
                acceptance, "command"
            ), unittest.mock.patch.object(
                acceptance, "verify_backups", return_value="gpg-symmetric-v1"
            ), unittest.mock.patch.object(
                acceptance, "live_state", return_value=self.current()
            ), unittest.mock.patch.object(
                acceptance, "verify_prometheus_history"
            ):
                path, payload = acceptance.acceptance(now=1700000100.0)
            self.assertEqual(payload["result"], "pass")
            self.assertEqual(payload["schema"], "lnd-ops/regtest-acceptance/v1")
            self.assertEqual(set(payload["checks"].values()), {"pass"})
            self.assertRegex(payload["redeploy_evidence_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_manual_gate_is_preserved(self):
        with unittest.mock.patch.object(
            acceptance, "command", side_effect=acceptance.ManualGate("unlock both wallets")
        ):
            with self.assertRaisesRegex(acceptance.ManualGate, "unlock both wallets"):
                acceptance.acceptance(now=1700000100.0)

    def test_stale_payment_is_a_manual_gate(self):
        now = 1700007200.0

        def fake_lncli(node, operation, *args):
            if operation == "getinfo":
                return {"identity_pubkey": f"02{node}"}
            if operation == "listchannels":
                return {"channels": [{"channel_point": "tx:0", "active": True, "capacity": "1000"}]}
            if operation == "listpayments":
                return {"payments": [{"status": "SUCCEEDED", "creation_date": str(int(now - 7200)), "payment_hash": "a" * 64}]}
            if operation == "listinvoices":
                return {"invoices": [{"state": "SETTLED", "settle_date": str(int(now - 10)), "r_hash": "a" * 64}]}
            raise AssertionError(operation)

        with unittest.mock.patch.object(acceptance, "lncli", side_effect=fake_lncli):
            with self.assertRaisesRegex(acceptance.ManualGate, "last hour"):
                acceptance.live_state(now)

    def test_current_identity_mismatch_fails(self):
        current = self.current()
        evidence = self.redeploy()
        current["nodes"]["lnd-0"]["node_key"] = "different"
        with self.assertRaisesRegex(acceptance.InvariantFailure, "node_key"):
            acceptance.verify_current_matches_redeploy(current, evidence)

    def test_malformed_latest_redeploy_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = pathlib.Path(directory)
            self.write_redeploy(evidence, name="regtest-redeploy-old.json")
            time.sleep(0.01)
            (evidence / "regtest-redeploy-new.json").write_text("{not-json")
            with unittest.mock.patch.object(acceptance, "EVIDENCE", evidence):
                with self.assertRaisesRegex(acceptance.InvariantFailure, "malformed"):
                    acceptance.latest_redeploy_evidence(1700000100.0)

    def test_old_redeploy_evidence_is_a_manual_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = pathlib.Path(directory)
            self.write_redeploy(evidence)
            with unittest.mock.patch.object(acceptance, "EVIDENCE", evidence):
                with self.assertRaisesRegex(acceptance.ManualGate, "older than 24 hours"):
                    acceptance.latest_redeploy_evidence(1700100000.0)

    def test_unrelated_recent_payments_do_not_count_as_bidirectional(self):
        now = 1700000100.0

        def fake_lncli(node, operation, *args):
            suffix = "a" if node == "lnd-0" else "b"
            if operation == "getinfo":
                return {"identity_pubkey": f"02{node}"}
            if operation == "listchannels":
                return {"channels": [{"channel_point": "tx:0", "active": True, "capacity": "1000"}]}
            if operation == "listpayments":
                return {"payments": [{"status": "SUCCEEDED", "creation_date": str(int(now - 10)), "payment_hash": suffix * 64}]}
            if operation == "listinvoices":
                return {"invoices": [{"state": "SETTLED", "settle_date": str(int(now - 10)), "r_hash": suffix * 64}]}
            raise AssertionError(operation)

        def fake_kubectl_json(*args):
            if "pvc" in args:
                return {"metadata": {"uid": "pvc"}}
            return {"metadata": {"uid": "cluster"}}

        with unittest.mock.patch.object(acceptance, "lncli", side_effect=fake_lncli), unittest.mock.patch.object(
            acceptance, "kubectl_json", side_effect=fake_kubectl_json
        ), unittest.mock.patch.object(
            acceptance, "kubectl", return_value=("a" * 64) + "  channel.backup\n"
        ):
            with self.assertRaisesRegex(acceptance.ManualGate, "settled by"):
                acceptance.live_state(now)


if __name__ == "__main__":
    unittest.main()
