import importlib.machinery
import importlib.util
import pathlib
import unittest
import unittest.mock


REPO = pathlib.Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("testnet_status", str(REPO / "ops/testnet-status"))
spec = importlib.util.spec_from_loader(loader.name, loader)
status = importlib.util.module_from_spec(spec)
loader.exec_module(status)


class TestnetStatusTests(unittest.TestCase):
    @staticmethod
    def response(operation):
        return {
            "getinfo": {"identity_pubkey": "02abc", "synced_to_chain": True, "block_height": 1},
            "walletbalance": {"confirmed_balance": "100000"},
            "listpeers": {"peers": [{"pub_key": "02peer"}]},
            "listchannels": {"channels": [{"active": True, "private": False, "capacity": "100000"}]},
            "listpayments": {"payments": [{"status": "SUCCEEDED"}]},
            "listinvoices": {"invoices": [{"state": "SETTLED"}]},
        }[operation]

    def test_complete_progress_passes(self):
        with unittest.mock.patch.object(status, "lncli", side_effect=lambda operation, *args: self.response(operation)):
            self.assertEqual(status.main([]), 0)

    def test_unsynced_node_is_manual_gate(self):
        def response(operation, *args):
            data = self.response(operation)
            if operation == "getinfo":
                data = dict(data, synced_to_chain=False)
            return data

        with unittest.mock.patch.object(status, "lncli", side_effect=response):
            self.assertEqual(status.main([]), 10)

    def test_malformed_capacity_fails(self):
        def response(operation, *args):
            data = self.response(operation)
            if operation == "listchannels":
                data = {"channels": [{"active": True, "private": False, "capacity": "bad"}]}
            return data

        with unittest.mock.patch.object(status, "lncli", side_effect=response):
            self.assertEqual(status.main([]), 1)


if __name__ == "__main__":
    unittest.main()
