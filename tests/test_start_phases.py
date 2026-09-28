"""Phase registration must not imply an implemented or deployed GitOps setup."""
import contextlib
import importlib.machinery
import io
import pathlib
import sys
import unittest
from unittest.mock import patch

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
                patch.object(start, 'guide_router', return_value='deferred') as router, \
                patch.object(start, 'guide_loop', return_value='partial') as loop, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(start.build_through(4, interactive=True), 10)
        router.assert_called_once_with(3, start.PHASES[2], allow_external_skip=True)
        loop.assert_called_once()
        self.assertIn('[3] PENDING', output.getvalue())
        self.assertIn('PAUSE: Phase 04', output.getvalue())

    def test_shifted_phases_keep_historical_verifiers(self):
        expected = [('faults', ('ops/phase6-acceptance',)),
                    ('kagent', ('ops/phase7-acceptance',)),
                    ('hosts', ('ops/verify-phase-evidence', 'phase8')),
                    ('demo', ('ops/verify-phase-evidence', 'phase9'))]
        self.assertEqual([(p['id'], p['probe']) for p in start.PHASES[8:]], expected)


if __name__ == '__main__':
    unittest.main()
