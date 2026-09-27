import contextlib
import importlib.machinery
import io
import pathlib
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'ops'))
cli = importlib.machinery.SourceFileLoader('router_channel_ui', str(REPO / 'ops/router-channel')).load_module()


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
        rpc = Mock(side_effect=[info, {'channels': []}, {'confirmed_balance': 200000}, {'peers': [{'pub_key': 'peer'}]}])
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
