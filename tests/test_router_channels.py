import copy
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ops"))
import router_channels as channels
from router_store import read, operation_lock

PEER = "02" + "a" * 64
SELF = "03" + "b" * 64
TXID = "c" * 64


class FakeLND:
    def __init__(self):
        self.calls = []
        self.fail_open = False
        self.channels = []
        self.pending = []
        self.closing = []
        self.closed = []
        self.utxos = [{"outpoint": {"txid_str": TXID, "output_index": 0}, "amount_sat": 190000,
                       "confirmations": 3, "address_type": "WITNESS_PUBKEY_HASH", "pk_script": "0014" + "a" * 40}]

    def __call__(self, command, *args):
        self.calls.append((command, args))
        if command == "getinfo":
            return {"testnet": True, "synced_to_chain": True, "identity_pubkey": SELF}
        if command == "listchannels":
            return {"channels": self.channels}
        if command == "pendingchannels":
            return {"pending_open_channels": self.pending, "waiting_close_channels": self.closing}
        if command == "closedchannels":
            return {"channels": self.closed}
        if command == "listpeers":
            return {"peers": [{"pub_key": PEER}]}
        if command == "walletbalance":
            return {"confirmed_balance": 190000, "reserved_balance_anchor_chan": 10000}
        if command == "listunspent":
            return {"utxos": self.utxos}
        if command == "listchaintxns":
            return {"transactions": []}
        if command == "openchannel":
            if self.fail_open:
                raise TimeoutError("response lost after submission")
            return {"funding_txid": TXID, "output_index": 1}
        raise AssertionError(command)


class ChannelOpenTests(unittest.TestCase):
    def setUp(self):
        self.rpc = FakeLND()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = pathlib.Path(self.directory.name)

    def preview(self):
        return channels.preview(PEER, 100000, 1, 3000, 200000, self.rpc)

    def test_approved_inputs_rate_amount_and_no_push_are_used(self):
        record = channels.submit(self.root, self.preview(), self.rpc)
        self.assertEqual(record["state"], "broadcast")
        invocation = [args for name, args in self.rpc.calls if name == "openchannel"][0]
        self.assertIn("--local_amt=100000", invocation)
        self.assertIn(f"--utxo={TXID}:0", invocation)
        self.assertIn("--sat_per_vbyte=1", invocation)
        self.assertIn("--push_amt=0", invocation)
        self.assertNotIn("--private", invocation)

    def test_lost_response_blocks_second_open_even_when_pending_is_empty(self):
        plan = self.preview()
        self.rpc.fail_open = True
        with self.assertRaises(TimeoutError):
            channels.submit(self.root, plan, self.rpc)
        self.assertEqual(read(self.root, "open-request.json")["state"], "uncertain")
        self.rpc.fail_open = False
        with self.assertRaisesRegex(ValueError, "중복"):
            channels.submit(self.root, plan, self.rpc)
        self.assertEqual(sum(name == "openchannel" for name, _ in self.rpc.calls), 1)

    def test_pending_channel_prevents_duplicate(self):
        self.rpc.pending = [{"channel": {"remote_node_pub": PEER, "capacity": 100000}}]
        with self.assertRaisesRegex(ValueError, "대기"):
            self.preview()

    def test_changed_utxo_requires_new_approval(self):
        plan = self.preview()
        self.rpc.utxos[0]["amount_sat"] += 1
        with self.assertRaisesRegex(ValueError, "다시 승인"):
            channels.submit(self.root, plan, self.rpc)
        self.assertFalse(any(name == "openchannel" for name, _ in self.rpc.calls))

    def test_total_budget_includes_unjournaled_channels(self):
        self.rpc.channels = [{"remote_pubkey": "other", "capacity": 150000}]
        with self.assertRaisesRegex(ValueError, "전체 채널 예산"):
            self.preview()

    def test_standard_input_bound_and_fee_cap(self):
        with self.assertRaises(ValueError):
            channels.funding_selection(self.rpc.utxos, 100000, 10, 3000)
        invalid = copy.deepcopy(self.rpc.utxos)
        invalid[0]["pk_script"] = "0020" + "d" * 64
        with self.assertRaises(ValueError):
            channels.funding_selection(invalid, 100000, 1, 3000)

    def test_actual_lncli_numeric_enum_and_string_outpoint(self):
        utxos = copy.deepcopy(self.rpc.utxos)
        utxos[0].update(address_type=0, outpoint=TXID + ":1")
        result = channels.funding_selection(utxos, 100000, 1, 3000)
        self.assertEqual(result["utxos"], [TXID + ":1"])

    def test_single_writer_lock(self):
        with operation_lock(self.root):
            with self.assertRaises(BlockingIOError):
                with operation_lock(self.root):
                    self.fail("second writer acquired lock")

    def test_reconcile_requires_recorded_identity(self):
        record = channels.submit(self.root, self.preview(), self.rpc)
        record["identity"] = "another wallet"
        from router_store import write
        write(self.root, "open-request.json", record)
        with self.assertRaisesRegex(ValueError, "identity"):
            channels.reconcile(self.root, self.rpc)

    def test_confirmed_channel_resolves_by_memo_not_peer_guess(self):
        record = channels.submit(self.root, self.preview(), self.rpc)
        self.rpc.channels = [{"remote_pubkey": PEER, "capacity": 100000, "memo": record["memo"],
                              "channel_point": TXID + ":1", "active": True}]
        resolved = channels.reconcile(self.root, self.rpc)
        self.assertEqual(resolved["state"], "active")

    def test_untrusted_record_symlink_rejected(self):
        (self.root / "source.json").write_text(json.dumps({}))
        (self.root / "open-request.json").symlink_to(self.root / "source.json")
        with self.assertRaises(OSError):
            read(self.root, "open-request.json")

    def test_lost_response_recovers_pending_memo_without_reopening(self):
        self.rpc.fail_open = True
        with self.assertRaises(TimeoutError):
            channels.submit(self.root, self.preview(), self.rpc)
        record = read(self.root, 'open-request.json')
        self.rpc.pending = [{'channel': {'remote_node_pub': PEER, 'capacity': 100000,
                                        'memo': record['memo'], 'channel_point': TXID + ':1'}}]
        result = channels.reconcile(self.root, self.rpc)
        self.assertEqual(result['state'], 'broadcast')
        self.assertEqual(result['channel_point'], TXID + ':1')
        self.assertEqual(sum(name == 'openchannel' for name, _ in self.rpc.calls), 1)

    def test_point_alone_does_not_override_wrong_peer_or_amount(self):
        for changes in ({'remote_pubkey': 'other'}, {'capacity': 100001}):
            record = channels.submit(self.root, self.preview(), self.rpc) if not read(self.root, 'open-request.json') else read(self.root, 'open-request.json')
            self.rpc.channels = [{'remote_pubkey': PEER, 'capacity': 100000, 'memo': record['memo'],
                                  'channel_point': TXID + ':1', 'active': True} | changes]
            with self.subTest(changes=changes):
                self.assertEqual(channels.reconcile(self.root, self.rpc)['state'], 'uncertain')

    def test_closing_channel_remains_blocked_until_confirmed_close(self):
        plan = self.preview()
        channels.submit(self.root, plan, self.rpc)
        self.rpc.closing = [{'channel': {'remote_node_pub': PEER, 'capacity': 100000,
                                        'channel_point': TXID + ':1'}}]
        self.assertEqual(channels.reconcile(self.root, self.rpc)['state'], 'closing')
        with self.assertRaisesRegex(ValueError, '중복'):
            channels.submit(self.root, plan, self.rpc)
        self.rpc.closing = []
        self.rpc.closed = [{'channel_point': TXID + ':1', 'remote_pubkey': PEER, 'capacity': 100000,
                            'close_height': 100, 'closing_tx_hash': 'd' * 64, 'close_type': 'COOPERATIVE_CLOSE'}]
        result = channels.reconcile(self.root, self.rpc)
        self.assertEqual(result['state'], 'closed')
        self.assertEqual(result['closing_txid'], 'd' * 64)
        self.assertEqual(sum(name == 'openchannel' for name, _ in self.rpc.calls), 1)

    def test_abandoned_canceled_or_unconfirmed_close_does_not_authorize_retry(self):
        channels.submit(self.root, self.preview(), self.rpc)
        base = {'channel_point': TXID + ':1', 'remote_pubkey': PEER, 'capacity': 100000,
                'close_height': 100, 'closing_tx_hash': 'd' * 64, 'close_type': 'COOPERATIVE_CLOSE'}
        for changes in ({'close_type': 'ABANDONED'}, {'close_type': 'FUNDING_CANCELED'}, {'close_height': 0},
                        {'closing_tx_hash': ''}, {'remote_pubkey': 'other'}):
            self.rpc.closed = [base | changes]
            with self.subTest(changes=changes):
                self.assertEqual(channels.reconcile(self.root, self.rpc)['state'], 'uncertain')

    def test_multiple_memo_matches_never_pick_an_arbitrary_funding_point(self):
        self.rpc.fail_open = True
        with self.assertRaises(TimeoutError):
            channels.submit(self.root, self.preview(), self.rpc)
        record = read(self.root, 'open-request.json')
        self.rpc.pending = [{'channel': {'remote_node_pub': PEER, 'capacity': 100000,
                                        'memo': record['memo'], 'channel_point': TXID + ':' + str(index)}} for index in (1, 2)]
        result = channels.reconcile(self.root, self.rpc)
        self.assertEqual(result['state'], 'uncertain')
        self.assertNotIn('channel_point', result)


if __name__ == "__main__":
    unittest.main()
