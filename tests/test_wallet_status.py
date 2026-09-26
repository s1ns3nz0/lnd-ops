import importlib.machinery
import importlib.util
import pathlib
import unittest
import unittest.mock


REPO = pathlib.Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("wallet_status", str(REPO / "ops/wallet-status"))
spec = importlib.util.spec_from_loader(loader.name, loader)
wallet_status = importlib.util.module_from_spec(spec)
loader.exec_module(wallet_status)


class WalletStatusTests(unittest.TestCase):
    def test_active_wallet_uses_an_existing_external_address(self):
        responses = {
            "state": {"state": "SERVER_ACTIVE"},
            "getinfo": {"identity_pubkey": "02node"},
            "walletbalance": {"confirmed_balance": "42"},
            "listchannels": {"channels": [{"active": True}, {"active": False}]},
            "listaddresses": {"account_with_addresses": [{"addresses": [
                {"address": "tb1existing", "internal": False}, {"address": "tb1change", "internal": True},
            ]}]},
        }
        with unittest.mock.patch.object(wallet_status, "lncli", side_effect=lambda _profile, _node, op: responses[op]):
            row = wallet_status.summary("testnet", "lnd-0")
        self.assertEqual(row["address"], "tb1existing")
        self.assertEqual(row["address_kind"], "외부 주소")
        self.assertEqual(row["confirmed_sat"], 42)
        self.assertEqual(row["active_channels"], 1)
        self.assertIn("https://www.btcgacha.com/", wallet_status.render([row]))
        self.assertIn("Mainnet Lightning sats faucet (12h)", wallet_status.render([row]))

    def test_missing_or_locked_wallet_does_not_expose_a_placeholder_address(self):
        with unittest.mock.patch.object(wallet_status, "lncli", return_value={"state": "NON_EXISTING"}):
            row = wallet_status.summary("testnet", "lnd-0")
        self.assertEqual(row, {"profile": "testnet", "node": "lnd-0", "state": "지갑 없음"})
        self.assertIn("지갑 없음", wallet_status.render([row]))

    def test_cluster_failure_is_not_reported_as_a_missing_wallet(self):
        with unittest.mock.patch.object(wallet_status, "lncli", return_value=None):
            row = wallet_status.summary("testnet", "lnd-0")
        self.assertEqual(row["state"], "상태 읽기 실패")

    def test_malformed_address_response_is_not_reported_as_an_absent_address(self):
        responses = {
            "state": {"state": "SERVER_ACTIVE"}, "getinfo": {"identity_pubkey": "02node"},
            "walletbalance": {"confirmed_balance": "1"}, "listchannels": {"channels": []},
            "listaddresses": {"account_with_addresses": "not-a-list"},
        }
        with unittest.mock.patch.object(wallet_status, "lncli", side_effect=lambda _profile, _node, op: responses[op]):
            row = wallet_status.summary("testnet", "lnd-0")
        self.assertEqual(row["state"], "상태 읽기 실패")

    def test_older_lnd_uses_an_existing_funded_address_when_listaddresses_is_unsupported(self):
        responses = {
            "state": {"state": "SERVER_ACTIVE"}, "getinfo": {"identity_pubkey": "02node"},
            "walletbalance": {"confirmed_balance": "11289"}, "listchannels": {"channels": []},
            "listaddresses": None,
            "listunspent": {"utxos": [{"address": "tb1existingfunded", "amount_sat": 11289}]},
        }
        with unittest.mock.patch.object(wallet_status, "lncli", side_effect=lambda _profile, _node, op: responses[op]):
            row = wallet_status.summary("testnet", "lnd-0")
        self.assertEqual(row["address"], "tb1existingfunded")
        self.assertEqual(row["address_kind"], "UTXO 주소")


if __name__ == "__main__":
    unittest.main()
