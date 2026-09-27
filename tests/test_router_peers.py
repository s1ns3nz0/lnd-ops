import pathlib
import sys
import subprocess
import tempfile
import unittest
import contextlib
import io
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ops"))
from router_peers import approve, reconnect, validate_peer, wizard
from router_store import read

KEY = "02" + "a" * 64
SELF = "03" + "b" * 64


class PeerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = pathlib.Path(self.directory.name)
        self.connected = []
        self.attempts = []
        self.identity = SELF

    def rpc(self, command, *args):
        if command == "getinfo":
            return {"testnet": True, "synced_to_chain": True, "identity_pubkey": self.identity}
        if command == "listpeers":
            return {"peers": [{"pub_key": key} for key in self.connected]}
        if command == "connect":
            self.attempts.append(args)
            raise RuntimeError("peer offline")
        self.fail(command)

    def test_unapproved_peers_are_never_contacted(self):
        reconnect(self.root, self.rpc, now=100)
        self.assertEqual(self.attempts, [])

    def test_empty_registration_cancels_without_address_or_mutation(self):
        with patch('builtins.input', return_value='') as ask, contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(wizard(self.root, self.rpc))
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(self.attempts, [])
        self.assertIsNone(read(self.root, 'peers.json'))

    def test_existing_channel_peer_is_hidden_and_rejected_if_typed(self):
        self.connected = [KEY]
        with patch('builtins.input', side_effect=[KEY, '']), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertFalse(wizard(self.root, self.rpc, excluded_peers={KEY}))
        self.assertNotIn('[1]', output.getvalue())
        self.assertIn('이미 채널이 있는 상대', output.getvalue())
        self.assertEqual(self.attempts, [])

    def test_bad_key_or_out_of_range_number_reprompts_before_address(self):
        with patch('builtins.input', side_effect=['1', 'bad-key', SELF, '']) as ask, contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(wizard(self.root, self.rpc))
        self.assertTrue(all('공개키' in c.args[0] for c in ask.call_args_list))
        self.assertIsNone(read(self.root, 'peers.json'))

    def test_filtered_number_selects_remaining_peer(self):
        other = '02' + 'c' * 64
        self.connected = [KEY, other]
        with patch('builtins.input', side_effect=['1', 'node.example:9735', 'CONNECT']), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(wizard(self.root, self.rpc, excluded_peers={KEY}))
        self.assertEqual(set(read(self.root, 'peers.json')['peers']), {other})

    def test_retries_back_off_and_stop_after_three_even_across_calls(self):
        approve(self.root, KEY, "node.example:9735", self.rpc)
        for now in (100, 101, 110, 115, 129, 130, 999, 1000):
            reconnect(self.root, self.rpc, now=now)
        self.assertEqual(len(self.attempts), 3)
        self.assertEqual(self.attempts[0], (KEY + "@node.example:9735",))
        self.assertEqual(read(self.root, "peers.json")["peers"][KEY]["state"], "needs_review")

    def test_observed_recovery_clears_failed_attempts(self):
        approve(self.root, KEY, "node.example:9735", self.rpc)
        reconnect(self.root, self.rpc, now=100)
        self.connected = [KEY]
        reconnect(self.root, self.rpc, now=101)
        self.assertEqual(read(self.root, "peers.json")["peers"][KEY]["attempts"], 0)

    def test_timeout_is_recorded_without_aborting_other_approved_peers(self):
        second = "02" + "d" * 64
        for key in (KEY, second):
            approve(self.root, key, "node.example:9735", self.rpc)
        def timeout_rpc(command, *args):
            if command == "connect":
                self.attempts.append(args)
                raise subprocess.TimeoutExpired("lncli", 30)
            return self.rpc(command, *args)
        events = reconnect(self.root, timeout_rpc, now=100)
        self.assertEqual(len(self.attempts), 2)
        self.assertEqual([event["state"] for event in events], ["retry_wait", "retry_wait"])
        self.assertEqual(read(self.root, "peers.json")["peers"][KEY]["attempts"], 1)

    def test_successful_connect_response_is_not_proof_of_connection(self):
        approve(self.root, KEY, "node.example:9735", self.rpc)
        def accepted_rpc(command, *args):
            if command == "connect":
                self.attempts.append(args)
                return {}
            return self.rpc(command, *args)
        for now in (100, 110, 130, 170, 1000):
            reconnect(self.root, accepted_rpc, now=now)
        self.assertEqual(len(self.attempts), 3)
        self.assertEqual(read(self.root, "peers.json")["peers"][KEY]["state"], "needs_review")

    def test_wallet_change_prevents_using_old_approval(self):
        approve(self.root, KEY, "node.example:9735", self.rpc)
        self.identity = "03" + "c" * 64
        with self.assertRaisesRegex(ValueError, "identity"):
            reconnect(self.root, self.rpc, now=100)
        self.assertEqual(self.attempts, [])

    def test_failed_observation_does_not_consume_connection_budget(self):
        approve(self.root, KEY, "node.example:9735", self.rpc)
        def unavailable_rpc(command, *args):
            if command == "listpeers":
                raise RuntimeError("observation unavailable")
            return self.rpc(command, *args)
        with self.assertRaisesRegex(RuntimeError, "observation unavailable"):
            reconnect(self.root, unavailable_rpc, now=100)
        self.assertEqual(self.attempts, [])
        self.assertEqual(read(self.root, "peers.json")["peers"][KEY]["attempts"], 0)

    def test_addresses_cannot_smuggle_command_options(self):
        for address in ("--foo", "host:9735 --other", "user@host:22", "https://node:9735", "node:0", "node:65536"):
            with self.assertRaises(ValueError):
                validate_peer(KEY, address)
        self.assertEqual(validate_peer(KEY, "[::1]:9735"), (KEY, "[::1]:9735"))


if __name__ == "__main__":
    unittest.main()
