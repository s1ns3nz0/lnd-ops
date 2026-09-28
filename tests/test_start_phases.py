"""Phase registration must not imply an implemented or deployed GitOps setup."""
import contextlib
import importlib.machinery
import io
import pathlib
import sys
import unittest
from unittest.mock import patch, Mock

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'ops'))
start = importlib.machinery.SourceFileLoader('phase_start', str(REPO / 'ops/start')).load_module()


class PhaseTests(unittest.TestCase):
    def test_gitops_uses_read_only_probe_and_exposes_explicit_menu(self):
        result = type('Result', (), {'returncode': 10, 'stderr': 'PENDING: Git 설정 필요', 'stdout': ''})()
        with patch.object(start.subprocess, 'run', return_value=result) as run:
            state, detail = start.inspect(7)
            self.assertEqual(state, 'partial')
            self.assertIn('Git 설정 필요', detail)
        self.assertEqual(run.call_args.args[0][-1], 'verify-auto')
        with patch('builtins.input', side_effect=['wsl', 'q']), patch.object(start, 'run_confirmed') as action, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(start.guide_gitops(8, start.PHASES[7]), 'partial')
        action.assert_not_called()

    def test_gitops_install_requires_explicit_confirmation(self):
        with patch('builtins.input', side_effect=['wsl', '2', 'q']), patch.object(start, 'run_confirmed') as action, contextlib.redirect_stdout(io.StringIO()):
            start.guide_gitops(8, start.PHASES[7])
        self.assertEqual(action.call_args.args[1], ('ops/flux-phase', 'install', '--host', 'wsl', '--confirm', 'INSTALL'))
        self.assertEqual(action.call_args.args[2], 'TYPE INSTALL')

    def test_cumulative_build_stops_before_later_phase_actions(self):
        def state(index):
            return ('complete', 'passed') if index < 7 else ('partial', 'not implemented')
        with patch.object(start, 'selection_gate', return_value=None), \
                patch.object(start, 'inspect', side_effect=state), \
                patch.object(start, 'applies_to_selected_workspace', return_value=True), \
                patch.object(start, 'execute') as execute, \
                patch.object(start, 'guide_evidence_phase') as guide, \
                patch.object(start, 'guide_gitops', return_value='partial'), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(start.build_through(12, interactive=True), 10)
        execute.assert_not_called()
        guide.assert_not_called()
        self.assertIn('PAUSE: Phase 08', output.getvalue())

    def test_router_deferral_advances_to_loop_but_remains_pending(self):
        def state(index):
            return ('complete', 'passed') if index < 2 else ('partial', 'pending')
        with patch.object(start, 'selection_gate', return_value=None), \
                patch.object(start, 'inspect', side_effect=state), \
                patch.object(start, 'applies_to_selected_workspace', return_value=True), \
                patch.object(start, 'defer_router_for_loop', return_value=False), \
                patch.object(start, 'guide_router', return_value='deferred') as router, \
                patch.object(start, 'guide_loop', return_value='partial') as loop, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(start.build_through(4, interactive=True), 10)
        router.assert_called_once_with(3, start.PHASES[2], allow_external_skip=True)
        loop.assert_called_once()
        self.assertIn('[3] PENDING', output.getvalue())
        self.assertIn('PAUSE: Phase 04', output.getvalue())

    def test_loop_entry_defers_router_before_opening_router_actions(self):
        for router_state in ('partial', 'missing'):
            with self.subTest(state=router_state), \
                    patch.object(start, 'selection_gate', return_value=None), \
                    patch.object(start, 'inspect', side_effect=[('complete', ''), ('complete', ''), (router_state, 'policy required'), ('partial', '')]), \
                    patch.object(start, 'applies_to_selected_workspace', return_value=True), \
                    patch.object(start, 'defer_router_for_loop', return_value=True) as defer, \
                    patch.object(start, 'guide_router') as router, \
                    patch.object(start, 'guide_loop', return_value='partial') as loop, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(start.build_through(4, interactive=True), 10)
                defer.assert_called_once_with('policy required', True)
                router.assert_not_called()
                loop.assert_called_once()

    def test_defer_requires_lnd_readiness_and_explicit_yes_without_loop_installed(self):
        good = {'chains': [{'chain': 'bitcoin', 'network': 'testnet'}], 'identity_pubkey': 'node',
                'synced_to_chain': True, 'synced_to_graph': True}
        for info, answer, expected in ((good, 'yes', True), (good, '', False),
                                      (dict(good, synced_to_chain=False), 'yes', False),
                                      (dict(good, chains=[]), 'yes', False)):
            api = Mock()
            api.lnd.side_effect = [info, {'confirmed_balance': '0'}]
            with patch('loop_api.API', return_value=api), patch.object(start.sys.stdin, 'isatty', return_value=True), \
                    patch('builtins.input', return_value=answer), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(start.defer_router_for_loop('policy required', True), expected)
            api.loop.assert_not_called()
            api.save.assert_not_called()

    def test_noninteractive_cannot_defer(self):
        with patch('loop_api.API') as api:
            self.assertFalse(start.defer_router_for_loop('pending', False))
            api.assert_not_called()

    def test_failed_lnd_probe_cannot_be_skipped(self):
        from loop_api import LoopError
        api = Mock()
        api.lnd.side_effect = LoopError('connection failed')
        with patch('loop_api.API', return_value=api), patch.object(start.sys.stdin, 'isatty', return_value=True), \
                patch('builtins.input') as prompt, contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(start.defer_router_for_loop('pending', True))
            prompt.assert_not_called()

    def test_shifted_phases_keep_historical_verifiers(self):
        expected = [('faults', ('ops/phase6-acceptance',)),
                    ('kagent', ('ops/phase7-acceptance',)),
                    ('hosts', ('ops/verify-phase-evidence', 'phase8')),
                    ('demo', ('ops/verify-phase-evidence', 'phase9'))]
        self.assertEqual([(p['id'], p['probe']) for p in start.PHASES[8:]], expected)


if __name__ == '__main__':
    unittest.main()
