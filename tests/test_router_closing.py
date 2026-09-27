import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'ops'))
from router_closing import preview, status, submit
from router_store import operation_lock, read

POINT = 'a' * 64 + ':1'


class ClosingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name) / 'router'
        self.channel = dict(channel_point=POINT, active=True, remote_pubkey='02' + 'b' * 64,
                            local_balance='23000', capacity='30000', pending_htlcs=[])
        self.pending = {}
        self.closed = []
        self.calls = []
        self.error = None
        self.identity = '03' + 'c' * 64

    def rpc(self, *args, **kwargs):
        self.calls.append(args)
        if args[0] == 'closechannel':
            if self.error:
                raise self.error
            return {'closing_txid': 'd' * 64}
        return {'getinfo': dict(testnet=True, synced_to_chain=True, identity_pubkey=self.identity),
                'listchannels': {'channels': [self.channel]}, 'pendingchannels': self.pending,
                'closedchannels': {'channels': self.closed}}[args[0]]

    def plan(self):
        return preview(POINT, 1, 2, self.rpc)

    def test_cooperative_close_bounds_fee_and_blocks_duplicate(self):
        plan = self.plan()
        self.assertEqual(submit(self.root, plan, self.rpc)['state'], 'closing')
        self.assertIn(('closechannel', '--chan_point=' + POINT, '--sat_per_vbyte=1', '--max_fee_rate=2'), self.calls)
        with self.assertRaises(ValueError):
            submit(self.root, plan, self.rpc)
        self.assertEqual(sum(c[0] == 'closechannel' for c in self.calls), 1)

    def test_lost_response_persists_and_empty_evidence_never_retries(self):
        plan = self.plan()
        self.error = TimeoutError('lost')
        with self.assertRaises(TimeoutError):
            submit(self.root, plan, self.rpc)
        self.assertEqual(read(self.root, 'close-requests.json')[0]['state'], 'uncertain')
        with self.assertRaises(ValueError):
            submit(self.root, plan, self.rpc)
        self.assertEqual(sum(c[0] == 'closechannel' for c in self.calls), 1)

    def test_changed_balance_or_identity_requires_new_approval(self):
        plan = self.plan()
        for field, value in [('local_balance', '22000'), ('remote_pubkey', '02' + 'e' * 64)]:
            original = self.channel[field]
            self.channel[field] = value
            with self.assertRaises(ValueError):
                submit(self.root, plan, self.rpc)
            self.channel[field] = original
        self.identity = '03' + 'f' * 64
        with self.assertRaises(ValueError):
            submit(self.root, plan, self.rpc)
        self.assertFalse(any(c[0] == 'closechannel' for c in self.calls))

    def test_offline_htlc_and_already_closing_block(self):
        self.channel['active'] = False
        with self.assertRaises(ValueError):
            self.plan()
        self.channel['active'] = True
        self.channel['pending_htlcs'] = [{}]
        with self.assertRaises(ValueError):
            self.plan()
        self.channel['pending_htlcs'] = []
        self.pending = {'waiting_close_channels': [{'channel': self.channel}]}
        with self.assertRaises(ValueError):
            self.plan()

    def test_confirmation_requires_closed_evidence_and_no_pending(self):
        submit(self.root, self.plan(), self.rpc)
        self.closed = [dict(channel_point=POINT, closing_tx_hash='d' * 64, close_height=0)]
        with operation_lock(self.root):
            self.assertEqual(status(self.root, self.rpc)[2][0]['state'], 'closing')
        self.closed[0]['close_height'] = 500
        self.pending = {'waiting_close_channels': [{'channel': self.channel}]}
        with operation_lock(self.root):
            self.assertEqual(status(self.root, self.rpc)[2][0]['state'], 'closing')
        self.pending = {}
        with operation_lock(self.root):
            self.assertEqual(status(self.root, self.rpc)[2][0]['state'], 'closed')

    def test_bad_fee_bounds(self):
        for rate, maximum in [(0, 1), (2, 1), (1, 10001), (True, 2)]:
            with self.assertRaises(ValueError):
                preview(POINT, rate, maximum, self.rpc)


class ClosingUITests(unittest.TestCase):
    def setUp(self):
        import importlib.machinery
        self.ui = importlib.machinery.SourceFileLoader('router_close_ui', str(pathlib.Path(__file__).resolve().parents[1] / 'ops/router-close')).load_module()

    def run_wizard(self, answers):
        import contextlib
        import io
        from unittest.mock import patch
        channel = dict(channel_point=POINT, active=True, remote_pubkey='peer', local_balance='23000', capacity='30000')
        plan = dict(identity='node', point=POINT, peer='peer', local_sat=23000, capacity_sat=30000, rate=1, maximum=1)
        output = io.StringIO()
        with patch.object(sys, 'argv', ['router-close']), patch.object(self.ui, 'operation_lock', return_value=contextlib.nullcontext()), \
             patch.object(self.ui, 'status', return_value=('node', [channel], [])), \
             patch.object(self.ui, 'preview', return_value=plan), patch.object(self.ui, 'submit', return_value=dict(plan, state='closing')) as send, \
             patch('builtins.input', side_effect=answers), contextlib.redirect_stdout(output):
            self.ui.main()
        return send, output.getvalue()

    def test_cancel_at_selection_and_final_never_sends(self):
        for answers in [[''], ['s'], ['1', '', '', ''], ['1', '', '', 'close']]:
            send, text = self.run_wizard(answers)
            send.assert_not_called()
            self.assertIn('취소됨', text)

    def test_only_uppercase_confirmation_sends(self):
        send, text = self.run_wizard(['1', '', '', 'CLOSE'])
        send.assert_called_once()
        self.assertIn('최대 1 sat/vB', text)
        self.assertIn('총 수수료 sat 상한은 아님', text)
        self.assertIn('종료 진행 중', text)
