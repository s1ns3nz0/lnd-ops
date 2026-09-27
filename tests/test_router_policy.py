import pathlib
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ops"))
from router_policy import target, validate
from router_store import read


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = pathlib.Path(self.directory.name)
        self.main = runpy.run_path(str(pathlib.Path(__file__).resolve().parents[1] / "ops/configure-router-policy"))["main"]
        self.updates = []
        self.fail_update = False
        self.testnet = True

    def rpc(self, command, *args):
        if command == "getinfo":
            return {"testnet": self.testnet, "synced_to_chain": True, "identity_pubkey": "router"}
        if command == "listchannels":
            return {"channels": [{"active": True, "private": False, "local_balance": 0,
                                  "capacity": 100000, "channel_point": f"tx:{index}"} for index in (0, 1)]}
        if command == "updatechanpolicy":
            self.assertEqual(read(self.root, "policy.json")["state"], "applying")
            self.updates.append(args)
            return {"failed_updates": [{"reason": "offline"}]} if self.fail_update else {}
        self.fail(command)

    def execute(self):
        with patch.dict(self.main.__globals__, lncli=self.rpc, state_directory=lambda: self.root):
            return self.main(["--confirm", "APPLY ROUTER POLICY", "--rate-ppm", "750"])

    def test_zero_local_balance_channel_gets_policy_and_saved_target(self):
        self.assertEqual(self.execute(), 0)
        self.assertEqual(len(self.updates), 2)
        self.assertIn("--fee_rate=0.00075", self.updates[0])
        self.assertEqual(target(self.root, "router")["rate_ppm"], 750)
        self.assertEqual(read(self.root, "policy.json")["state"], "applied")

    def test_partial_rpc_failure_keeps_target_without_claiming_applied(self):
        self.fail_update = True
        self.assertEqual(self.execute(), 1)
        self.assertEqual(read(self.root, "policy.json")["state"], "applying")
        self.assertEqual(len(self.updates), 1)

    def test_mainnet_guard_precedes_policy_changes(self):
        self.testnet = False
        self.assertEqual(self.execute(), 1)
        self.assertEqual(self.updates, [])
        self.assertIsNone(read(self.root, "policy.json"))

    def test_saved_policy_cannot_cross_wallet_identity(self):
        self.execute()
        with self.assertRaisesRegex(ValueError, "identity"):
            target(self.root, "other-wallet")

    def test_invalid_policy_is_rejected(self):
        for value in (-1, True, 1000001):
            with self.assertRaises(ValueError):
                validate({"base_msat": value, "rate_ppm": 500, "min_htlc_msat": 1})


if __name__ == "__main__":
    unittest.main()
