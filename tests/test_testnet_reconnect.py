import importlib.machinery
import importlib.util
import pathlib
import unittest
import unittest.mock


REPO = pathlib.Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("testnet_reconnect", str(REPO / "ops/testnet-reconnect-check"))
spec = importlib.util.spec_from_loader(loader.name, loader)
reconnect = importlib.util.module_from_spec(spec)
loader.exec_module(reconnect)


class TestnetReconnectTests(unittest.TestCase):
    def test_requires_explicit_disruption_confirmation(self):
        self.assertEqual(reconnect.main([]), 2)

    def test_active_channel_peer_reconnects(self):
        key = "02" + "a" * 64
        peers = [
            {key: {"pub_key": key, "address": "198.51.100.1:9735"}},
            {},
            {key: {"pub_key": key, "address": "198.51.100.1:9735"}},
        ]
        channels = {"channels": [{"remote_pubkey": key, "active": True, "capacity": "100000"}]}
        with unittest.mock.patch.object(reconnect, "connected_peers", side_effect=peers), unittest.mock.patch.object(
            reconnect, "call", return_value=channels
        ) as call, unittest.mock.patch.object(reconnect.time, "sleep"):
            self.assertEqual(reconnect.main(["--confirm-peer-disruption"]), 0)
        call.assert_any_call("disconnectpeer", key, json_output=False)

    def test_missing_active_channel_is_manual_gate(self):
        with unittest.mock.patch.object(reconnect, "connected_peers", return_value={}), unittest.mock.patch.object(
            reconnect, "call", return_value={"channels": []}
        ):
            self.assertEqual(reconnect.main(["--confirm-peer-disruption"]), 10)


if __name__ == "__main__":
    unittest.main()
