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
    def drive(self, results, answers=(), policy_approved=True, allow_external_skip=False, confirmation="no"):
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

        with patch('builtins.input', return_value=confirmation) as confirm, \
             patch.object(start, 'StatusWorker', return_value=worker), \
             patch.object(start.sys, 'stdin', stdin), patch.object(start.time, 'time', return_value=100), \
             patch.object(start.time, 'sleep'), patch.object(start.select, 'select', return_value=([stdin], [], [])), \
             patch.object(start, 'run_testnet_unlock', side_effect=lambda: events.append('unlock')), \
             patch.object(start, 'run_router_wizard', side_effect=lambda: events.append('exposure')), \
             patch.object(start.subprocess, 'run', side_effect=command), \
             patch.object(start, 'run_confirmed', side_effect=policy), \
             patch.object(start, 'render_router_snapshot', return_value=None) as render, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            outcome = start.guide_router(3, start.PHASES[2], allow_external_skip=allow_external_skip)
        worker.close.assert_called_once()
        return outcome, events, worker, render, output.getvalue()

    def test_external_only_can_be_deferred_without_marking_complete(self):
        current = status('external_required', ready=True, forwarding_proof='observed')
        outcome, events, _, _, output = self.drive(
            [current], answers=['q'], allow_external_skip=True, confirmation='yes')
        self.assertEqual(outcome, 'deferred')
        self.assertFalse(current['complete'])
        self.assertEqual(events, [])
        self.assertIn('미완료', output)

    def test_external_skip_requires_explicit_yes(self):
        for answer in ('', 'no', 'y'):
            with self.subTest(answer=answer):
                outcome, events, _, _, _ = self.drive(
                    [status('external_required', ready=True, forwarding_proof='observed')],
                    answers=['q'], allow_external_skip=True, confirmation=answer)
                self.assertEqual(outcome, 'partial')
                self.assertEqual(events, [])

    def test_other_blockers_and_stale_results_cannot_be_deferred(self):
        for current in (status('proof_required', ready=True),
                        status('external_required', ready=False, forwarding_proof='observed'),
                        status('external_required', ready=True, forwarding_proof='observed', checked_at=69),
                        status('external_required', ready=True, forwarding_proof='observed', checked_at=101)):
            with self.subTest(current=current):
                outcome, _, _, _, _ = self.drive(
                    [current], answers=['q'], allow_external_skip=True, confirmation='yes')
                self.assertEqual(outcome, 'partial')

    def test_noninteractive_external_skip_is_not_automatic(self):
        outcome, _, _, _, _ = self.drive(
            [status('external_required', ready=True, forwarding_proof='observed'), KeyboardInterrupt()],
            allow_external_skip=True, confirmation='yes')
        self.assertEqual(outcome, 'partial')

    def test_full_sequence_waits_for_each_verified_result(self):
        results = [status(code) for code in (
            'wallet_locked', 'syncing', 'exposure_required', 'peer_disconnected',
            'channel_required', 'funding_pending', 'graph_pending', 'policy_required',
            'liquidity_required', 'proof_required', 'external_required')]
        results.append(status('complete', ready=True, complete=True, forwarding_proof='verified',
                              external_reachability='operator_attested', external_expires_at=200))
        outcome, events, worker, render, output = self.drive(results)
        self.assertEqual(outcome, 'complete')
        self.assertEqual(events, [])
        self.assertEqual(worker.tick.call_count, len(results))
        self.assertEqual(worker.request_now.call_count, len(events))
        self.assertEqual([call.args[0]['code'] for call in render.call_args_list],
                         [result['code'] for result in results[:-1]])
        self.assertEqual(output.count('완료: Router'), 1)

    def test_action_success_is_not_completion_or_automatic_resubmission(self):
        outcome, events, worker, _, output = self.drive(
            [status('channel_required')] * 3, answers=['a', 'q'])
        self.assertEqual(outcome, 'partial')
        self.assertEqual(events, ['router-channel'])
        self.assertEqual(worker.tick.call_count, 3)
        self.assertNotIn('완료: Router', output)

    def test_single_node_wait_never_prompts_for_ssh_or_starts_payment(self):
        outcome, events, _, _, output = self.drive(
            [status('proof_required', ready=True)], answers=['q'])
        self.assertEqual(outcome, 'partial')
        self.assertEqual(events, [])

    def test_external_check_is_explicit_and_never_automatic(self):
        outcome, events, _, _, _ = self.drive(
            [status('external_required'), status('external_required')], answers=['e', 'q'])
        self.assertEqual(outcome, 'partial')
        self.assertEqual(events, ['router-observation'])

    def test_declined_policy_waits_and_retries_only_on_explicit_input(self):
        outcome, events, worker, _, output = self.drive(
            [status('policy_required')] * 5, answers=['a', 'a', 'q'], policy_approved=False)
        self.assertEqual(outcome, 'partial')
        self.assertEqual(events, ['policy', 'policy'])
        self.assertEqual(worker.request_now.call_count, 4)
        self.assertNotIn('완료: Router', output)

    def test_refresh_never_opens_settings_and_detail_keeps_polling(self):
        outcome, events, worker, render, _ = self.drive(
            [status('peer_disconnected'), status('syncing'), status('proof_required', ready=True)],
            answers=['d', 'r', 'q'])
        self.assertEqual(outcome, 'partial')
        self.assertEqual(events, [])
        self.assertEqual(worker.tick.call_count, 3)
        self.assertEqual([c.kwargs['compact'] for c in render.call_args_list], [True, False, False])
        worker.request_now.assert_called_once()

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
