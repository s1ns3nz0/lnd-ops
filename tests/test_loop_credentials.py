"""Credential creation and the Phase 4 menu without touching live wallets."""
import contextlib
import importlib.machinery
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ops'))
import loop_credentials as credentials
start = importlib.machinery.SourceFileLoader('loop_start', str(ROOT / 'ops/start')).load_module()


class CredentialTests(unittest.TestCase):
    def responses(self, token=None):
        return [Mock(returncode=0, stdout=json.dumps({
                    'identity_pubkey': '02' + 'ab' * 32,
                    'chains': [{'chain': 'bitcoin', 'network': 'testnet'}]})),
                Mock(returncode=0, stdout=json.dumps({'method_permissions': {
                    uri: {} for uri in credentials.LOOP_RPC_URIS}})),
                Mock(returncode=0, stdout=token or ('02' + 'cd' * 50))]

    def test_private_binary_file_and_explicit_rpc_scope(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
                credentials.subprocess, 'run', side_effect=self.responses()) as run:
            result = credentials.create_loop_macaroon(directory, {'KUBECONFIG': '/selected'})
            self.assertEqual(result.read_bytes(), bytes.fromhex('02' + 'cd' * 50))
            self.assertEqual(stat.S_IMODE(result.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(result.parent.stat().st_mode), 0o700)
            args = run.call_args.args[0]
            self.assertIn('bakemacaroon', args)
            self.assertTrue(all(p.startswith('uri:/') for p in args[args.index('bakemacaroon')+1:]))
            self.assertEqual(run.call_args.kwargs['env']['KUBECONFIG'], '/selected')
            self.assertTrue(run.call_args.kwargs['capture_output'])
            for forbidden in ('SendCoins', 'OpenChannel', 'BakeMacaroon', 'CloseChannel'):
                self.assertFalse(any(forbidden in uri for uri in credentials.LOOP_RPC_URIS))

    def test_wrong_network_and_missing_rpc_never_mint(self):
        for stage in ('network', 'permissions'):
            results = self.responses()
            if stage == 'network':
                results[0].stdout = results[0].stdout.replace('testnet', 'mainnet')
            else:
                results[1].stdout = '{"method_permissions": {}}'
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory, patch.object(
                    credentials.subprocess, 'run', side_effect=results) as run:
                with self.assertRaises(credentials.CredentialError):
                    credentials.create_loop_macaroon(directory, {})
                self.assertFalse(any('bakemacaroon' in c.args[0] for c in run.call_args_list))

    def test_mint_failure_and_bad_output_leave_no_file_or_secret_in_error(self):
        for bad in (Mock(returncode=1, stdout='secret-value', stderr='secret-value'),
                    Mock(returncode=0, stdout='secret-value')):
            results = self.responses(); results[2] = bad
            with tempfile.TemporaryDirectory() as directory, patch.object(
                    credentials.subprocess, 'run', side_effect=results):
                with self.assertRaises(credentials.CredentialError) as error:
                    credentials.create_loop_macaroon(directory, {})
                self.assertNotIn('secret-value', str(error.exception))
                self.assertEqual(list((Path(directory) / 'credentials').iterdir()), [])

    def test_existing_files_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
                credentials.subprocess, 'run', side_effect=self.responses() + self.responses()):
            first = credentials.create_loop_macaroon(directory, {})
            second = credentials.create_loop_macaroon(directory, {})
            self.assertNotEqual(first, second)
            self.assertTrue(first.is_file())


class LoopMenuTests(unittest.TestCase):
    def drive(self, answers, states=None, error=None):
        with patch.object(start, 'inspect', side_effect=states or [('partial', 'enable Loop')] * 5), \
                patch('builtins.input', side_effect=answers), \
                patch.object(credentials, 'create_loop_macaroon', return_value=Path('/private/loop.macaroon'), side_effect=error) as create, \
                patch.object(start, 'run_confirmed', return_value=True) as deploy, \
                patch('loop_ui.interactive', return_value='complete'), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            outcome = start.guide_loop(4, start.PHASES[3])
        return outcome, create, deploy, output.getvalue()

    def test_new_credential_flows_to_installer(self):
        outcome, create, deploy, output = self.drive(['1', 'yes'], [
            ('partial', 'enable Loop'), ('complete', 'OK')])
        self.assertEqual(outcome, 'complete')
        create.assert_called_once()
        self.assertEqual(deploy.call_args.args[1], ('ops/enable-loop', '--macaroon', '/private/loop.macaroon'))
        self.assertIn('저장 완료', output)

    def test_decline_cancel_eof_and_invalid_input_do_not_create_or_deploy(self):
        for answers in (['q'], ['1', '', 'q'], ['?', 'q'], [EOFError()]):
            with self.subTest(answers=answers):
                outcome, create, deploy, _ = self.drive(answers)
                self.assertEqual(outcome, 'partial')
                create.assert_not_called(); deploy.assert_not_called()

    def test_creation_failure_does_not_deploy(self):
        _, _, deploy, output = self.drive(['1', 'yes', 'q'], error=credentials.CredentialError('생성 실패'))
        deploy.assert_not_called()
        self.assertIn('생성 실패', output)

    def test_existing_file_is_passed_without_generation(self):
        with tempfile.NamedTemporaryFile() as file:
            outcome, create, deploy, _ = self.drive(['2', file.name], [
                ('partial', 'enable Loop'), ('complete', 'OK')])
        create.assert_not_called()
        self.assertEqual(deploy.call_args.args[1][-1], file.name)
        self.assertEqual(outcome, 'complete')


if __name__ == '__main__':
    unittest.main()
