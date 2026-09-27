"""Phase 3 orchestration across verifier states, without live mutations."""
import contextlib
import importlib.machinery
import io
import pathlib
import sys
import unittest
from unittest.mock import Mock, patch

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'ops'))
start = importlib.machinery.SourceFileLoader('router_interaction_start', str(REPO / 'ops/start')).load_module()


def status(code, **values):
    return {'schema': 'lnd-ops/router-status/v1', 'code': code, 'checked_at': 100,
            'message': code, 'ready': False, 'complete': False, 'channels': [], **values}


class RouterInteractionTests(unittest.TestCase):
    def drive(self, results, answers=(), policy_approved=True):
        worker = Mock()
        worker.tick.side_effect = results
        stdin = Mock()
        stdin.isatty.return_value = bool(answers)
        stdin.readline.side_effect = [answer + '\n' for answer in answers]
        events = []

        def command(argv, **kwargs):
            events.append(pathlib.Path(argv[0]).name)
            return Mock(returncode=0)

        def policy(*args, **kwargs):
            events.append('policy')
            return policy_approved

        with patch.object(start, 'StatusWorker', return_value=worker), \
             patch.object(start.sys, 'stdin', stdin), patch.object(start.time, 'time', return_value=100), \
             patch.object(start.time, 'sleep'), patch.object(start.select, 'select', return_value=([stdin], [], [])), \
             patch.object(start, 'run_testnet_unlock', side_effect=lambda: events.append('unlock')), \
             patch.object(start, 'run_router_wizard', side_effect=lambda: events.append('exposure')), \
             patch.object(start.subprocess, 'run', side_effect=command), \
             patch.object(start, 'run_confirmed', side_effect=policy), \
             patch.object(start, 'render_router_snapshot', return_value=None) as render, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            outcome = start.guide_router(3, start.PHASES[2])
        worker.close.assert_called_once()
        return outcome, events, worker, render, output.getvalue()

    def test_full_sequence_waits_for_each_verified_result(self):
        results = [status(code) for code in (
            'wallet_locked', 'syncing', 'exposure_required', 'peer_disconnected',
            'channel_required', 'funding_pending', 'graph_pending', 'policy_required',
            'liquidity_required', 'proof_required', 'external_required')]
        results.append(status('complete', ready=True, complete=True, forwarding_proof='verified',
                              external_reachability='operator_attested', external_expires_at=200))
        outcome, events, worker, render, output = self.drive(results)
        self.assertEqual(outcome, 'complete')
        self.assertEqual(events, ['unlock', 'exposure', 'router-peers', 'router-channel',
                                  'policy', 'router-proof', 'router-observation'])
        self.assertEqual(worker.tick.call_count, len(results))
        self.assertEqual(worker.request_now.call_count, len(events))
        self.assertEqual([call.args[0]['code'] for call in render.call_args_list],
                         ['syncing', 'funding_pending', 'graph_pending', 'liquidity_required'])
        self.assertEqual(output.count('완료: Router'), 1)

    def test_action_success_is_not_completion_or_automatic_resubmission(self):
        outcome, events, worker, _, output = self.drive(
            [status('proof_required'), status('proof_required')], answers=['q'])
        self.assertEqual(outcome, 'partial')
        self.assertEqual(events, ['router-proof'])
        self.assertEqual(worker.tick.call_count, 2)
        self.assertNotIn('완료: Router', output)

    def test_declined_policy_waits_and_retries_only_on_explicit_input(self):
        outcome, events, worker, _, output = self.drive(
            [status('policy_required')] * 4, answers=['r', 'q'], policy_approved=False)
        self.assertEqual(outcome, 'partial')
        self.assertEqual(events, ['policy', 'policy'])
        self.assertEqual(worker.request_now.call_count, 3)
        self.assertNotIn('완료: Router', output)

    def test_query_error_preserves_snapshot_until_operator_interrupts(self):
        initial = status('funding_pending', channels=[{'point': 'tx:0', 'active': False, 'private': False}])
        error = {'code': 'query_error', 'message': 'transport unavailable', 'attempted_at': 101}
        outcome, events, _, render, output = self.drive([initial, error, KeyboardInterrupt()])
        self.assertEqual(outcome, 'partial')
        self.assertEqual(events, [])
        error_snapshot = render.call_args_list[1].args[0]
        self.assertEqual(error_snapshot['channels'], initial['channels'])
        self.assertEqual(error_snapshot['code'], 'query_error')
        self.assertNotIn('완료: Router', output)

    def test_stale_or_future_completion_keeps_waiting_for_fresh_verification(self):
        for checked_at, expiry in ((69, 200), (101, 200), (100, 100)):
            with self.subTest(checked_at=checked_at, expiry=expiry):
                outcome, events, worker, _, output = self.drive(
                    [status('complete', complete=True, checked_at=checked_at, external_expires_at=expiry),
                     status('syncing')], answers=['q'])
                self.assertEqual(outcome, 'partial')
                self.assertEqual(events, [])
                worker.request_now.assert_called_once()
                self.assertNotIn('완료: Router', output)


if __name__ == '__main__':
    unittest.main()
