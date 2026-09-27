import contextlib
import importlib.machinery
import io
import pathlib
import os
import subprocess
import sys
import unittest
import unicodedata
from unittest.mock import Mock, patch

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'ops'))
cli = importlib.machinery.SourceFileLoader('router_channel_ui', str(REPO / 'ops/router-channel')).load_module()


UTXO = {'amount_sat': 179620, 'confirmations': 3, 'address_type': 4,
        'pk_script': '5120' + 'a' * 64, 'outpoint': {'txid_str': 'b' * 64, 'output_index': 0}}


class ChannelInputTests(unittest.TestCase):
    def test_insufficient_balance_stops_before_amount_approval(self):
        rpc = Mock(side_effect=[
            {'testnet': True, 'synced_to_chain': True, 'identity_pubkey': 'self'},
            {'channels': []}, {'confirmed_balance': 36420, 'reserved_balance_anchor_chan': 10000},
            {'peers': [{'pub_key': 'peer', 'address': 'host:9735'}]}, {'required_reserve': '20000'}])
        with patch.object(cli, 'operation_lock', return_value=contextlib.nullcontext()), \
                patch.object(cli, 'reconcile', return_value=None), patch.object(cli, 'call', rpc), \
                patch('builtins.input', return_value='1') as ask, patch.object(cli, 'submit') as submit, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, '6,580 sat 부족'):
                cli.wizard()
        self.assertEqual(ask.call_count, 1)
        submit.assert_not_called()

    def test_no_distinct_peer_passes_exclusions_and_reports_cancellation(self):
        rpc = Mock(side_effect=[
            {'testnet': True, 'synced_to_chain': True, 'identity_pubkey': 'self'},
            {'channels': [{'remote_pubkey': 'existing'}]}, {'confirmed_balance': 30920},
            {'peers': [{'pub_key': 'existing', 'address': 'host:9735'}]}])
        with patch.object(cli, 'operation_lock', return_value=contextlib.nullcontext()), \
                patch.object(cli, 'reconcile', return_value=None), patch.object(cli, 'call', rpc), \
                patch.object(cli, 'peer_wizard', return_value=False) as register, \
                patch.object(cli, 'submit') as submit, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.wizard(), 10)
        self.assertEqual(register.call_args.kwargs, {'excluded_peers': {'existing'}})
        self.assertIn('등록을 취소했습니다', output.getvalue())
        self.assertNotIn('연결 요청을 처리했습니다', output.getvalue())
        submit.assert_not_called()

    def test_lower_balance_default_preserves_reserved_and_locked_funds(self):
        rpc = Mock(side_effect=[
            {'testnet': True, 'synced_to_chain': True, 'identity_pubkey': 'self'},
            {'channels': []}, {'confirmed_balance': 90000, 'reserved_balance_anchor_chan': 10000, 'locked_balance': 20000},
            {'peers': [{'pub_key': 'peer'}]}, {'required_reserve': '20000'}, {'utxos': [UTXO]}, {}])
        plan = {'peer': 'peer', 'fee_upper_bound_sat': 2200, 'committed_sat': 0}
        with patch.object(cli, 'operation_lock', return_value=contextlib.nullcontext()), \
             patch.object(cli, 'reconcile', return_value=None), patch.object(cli, 'call', rpc), \
             patch.object(cli, 'preview', return_value=plan) as preview, patch.object(cli, 'submit') as submit, \
             patch('builtins.input', side_effect=['1', '', '', '', '', 's']), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.wizard(), 10)
        preview.assert_called_once_with('peer', 47000, 1, 3000, 47000)
        submit.assert_not_called()

    def test_enter_defaults_include_reserved_funds_and_pending_capacity_but_never_approve(self):
        rpc = Mock(side_effect=[
            {'testnet': True, 'synced_to_chain': True, 'identity_pubkey': 'self'},
            {'channels': [{'capacity': '160000', 'remote_pubkey': 'old'}]},
            {'confirmed_balance': '190909', 'reserved_balance_anchor_chan': '10000'},
            {'peers': [{'pub_key': 'peer', 'address': 'host:9735'}]},
            {'required_reserve': '20000'},
            {'utxos': [UTXO]}, {'pending_open_channels': [{'channel': {'capacity': '30000'}}]}])
        plan = {'peer': 'peer', 'fee_upper_bound_sat': 2200, 'committed_sat': 190000}
        with patch.object(cli, 'operation_lock', return_value=contextlib.nullcontext()), \
             patch.object(cli, 'reconcile', return_value=None), patch.object(cli, 'call', rpc), \
             patch.object(cli, 'preview', return_value=plan) as preview, patch.object(cli, 'submit') as submit, \
             patch('builtins.input', side_effect=['1', '', '', '', '', '']), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.wizard(), 10)
        preview.assert_called_once_with('peer', 100000, 1, 3000, 290000)
        submit.assert_not_called()
        self.assertIn('취소됨 · 새 개설 요청 없음', output.getvalue())
        self.assertIn('선택: 100,000', output.getvalue())
        self.assertIn('선택: 290,000', output.getvalue())

    def test_typo_reprompts_and_only_uppercase_open_approves(self):
        plan = {'peer': 'peer', 'fee_upper_bound_sat': 2200, 'committed_sat': 160000}
        with patch('builtins.input', side_effect=['open', 'yes', 'OPEN']) as ask, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertTrue(cli.confirm_open(plan, 100000, 1, 3000, 260000))
        self.assertEqual(ask.call_count, 3)
        self.assertIn('아직 개설 전', output.getvalue())

    def test_confirmation_wraps_full_peer_key_in_narrow_terminal(self):
        peer = '02' + 'a' * 64
        plan = {'peer': peer, 'fee_upper_bound_sat': 2200, 'committed_sat': 160000}
        with patch.object(cli.shutil, 'get_terminal_size', return_value=os.terminal_size((40, 24))), \
             patch('builtins.input', return_value='s'), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertFalse(cli.confirm_open(plan, 100000, 1, 3000, 260000))
        rows = output.getvalue().splitlines()
        self.assertTrue(all(sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in row) <= 39 for row in rows))
        self.assertIn(peer, ''.join(row.strip() for row in rows))

    def test_numeric_override_accepts_grouping_and_rejects_nonpositive_values(self):
        with patch('builtins.input', side_effect=['0', '-1', '50,000']), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.positive_integer('금액', 100000), 50000)


class ChannelBackupStatusTests(unittest.TestCase):
    def test_status_uses_read_only_helper_and_never_prints_hashes(self):
        for code, message in ((0, '일치합니다'), (10, '저장 기록이 없습니다'), (1, '일치를 확인하지 못했습니다')):
            with self.subTest(code=code), \
                 patch.object(cli.subprocess, 'run', return_value=Mock(returncode=code, stdout='private diagnostic', stderr='')) as run, \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                cli.show_backup_status()
            self.assertEqual(run.call_args.args[0],
                             [str(REPO / 'ops/backup-status-encrypted'), 'testnet', 'lnd-0', '--read-only'])
            self.assertEqual(run.call_args.kwargs['timeout'], 15)
            self.assertIn(message, output.getvalue())
            self.assertNotIn('private diagnostic', output.getvalue())
            self.assertIn('개설 대기 채널이 백업에 포함됐다는 뜻은 아닙니다', output.getvalue())
            self.assertIn('외부 사본·복구 성공을 증명하지 않습니다', output.getvalue())

    def test_backup_timeout_does_not_escape_as_funding_failure(self):
        with patch.object(cli.subprocess, 'run', side_effect=subprocess.TimeoutExpired('backup', 15)), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            cli.show_backup_status()
        self.assertIn('채널 개설 결과와 별개', output.getvalue())

    def test_outstanding_request_reports_backup_without_submitting_again(self):
        for state in ('submitting', 'uncertain', 'broadcast', 'closing'):
            record = {'state': state, 'memo': 'test-request', 'peer': 'peer', 'amount_sat': 100000}
            with self.subTest(state=state), patch.object(cli, 'operation_lock', return_value=contextlib.nullcontext()), \
                 patch.object(cli, 'reconcile', return_value=record), patch.object(cli, 'submit') as submit, \
                 patch.object(cli, 'show_backup_status') as backup, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.wizard(), 10)
            submit.assert_not_called()
            backup.assert_called_once()

    def test_successful_submission_survives_backup_lookup_failure(self):
        events = []
        info = {'testnet': True, 'synced_to_chain': True, 'identity_pubkey': 'self'}
        rpc = Mock(side_effect=[info, {'channels': []}, {'confirmed_balance': 200000},
                               {'peers': [{'pub_key': 'peer'}]}, {'required_reserve': '20000'}, {'utxos': [UTXO]}, {}])
        plan = {'peer': 'peer', 'fee_upper_bound_sat': 2200, 'committed_sat': 0}

        def submit(*args):
            events.append('funding')
            return {'channel_point': 'tx:0'}

        def backup(*args, **kwargs):
            events.append('backup')
            raise subprocess.TimeoutExpired('backup', 15)

        with patch.object(cli, 'operation_lock', return_value=contextlib.nullcontext()), \
             patch.object(cli, 'reconcile', return_value=None), patch.object(cli, 'call', rpc), \
             patch.object(cli, 'preview', return_value=plan), patch.object(cli, 'submit', side_effect=submit), \
             patch.object(cli.subprocess, 'run', side_effect=backup), \
             patch('builtins.input', side_effect=['1', '100000', '1', '3000', '200000', 'OPEN']), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.wizard(), 10)
        self.assertEqual(events, ['funding', 'backup'])
        self.assertIn('funding 요청 완료: tx:0', output.getvalue())
        self.assertNotIn('개설 보류', output.getvalue())


if __name__ == '__main__':
    unittest.main()
