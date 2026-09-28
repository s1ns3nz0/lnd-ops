"""Failure, budget and duplicate-submission contracts; no real funds or servers."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ops'))
from loop_api import LoopError
from loop_ops import Operations


class FakeAPI:
    def __init__(self):
        self.binding_value = {'namespace_uid': 'cluster-a', 'identity': '02' + 'ab' * 32}
        self.document = None
        self.revision = 0
        self.swap_list = []
        self.posts = []
        self.params = {}
        self.fail_post = False
        self.conflict = False
        self.channel = {'scid': '12345', 'chan_id': 'abcdef', 'active': True,
                        'remote_pubkey': '03' + 'cd' * 32, 'local_balance': '80000',
                        'remote_balance': '20000', 'local_chan_reserve_sat': '1000',
                        'remote_chan_reserve_sat': '1000', 'pending_htlcs': []}
        self.miner = '100'

    def binding(self): return copy.deepcopy(self.binding_value)
    def load(self): return copy.deepcopy(self.document)

    def save(self, document):
        if self.conflict or document['metadata'].get('resourceVersion') != (str(self.revision) if self.revision else None):
            raise LoopError('resourceVersion conflict')
        self.revision += 1
        self.document = copy.deepcopy(document)
        self.document['metadata']['resourceVersion'] = str(self.revision)
        return self.load()

    def lnd(self, command):
        if command == 'listchannels': return {'channels': [copy.deepcopy(self.channel)]}
        if command == 'walletbalance':
            return {'confirmed_balance': '200000', 'reserved_balance_anchor_chan': '20000', 'locked_balance': '0'}
        raise AssertionError(command)

    def loop(self, path, body=None):
        if body is not None:
            self.posts.append((path, body))
            if self.fail_post: raise LoopError('timeout')
            self.swap_list.append({'id': 'swap1', 'label': body['label'], 'amt': body['amt'],
                                   'type': 'LOOP_' + path.rsplit('/', 1)[1].upper(), 'state': 'INITIATED'})
            return {'id': 'swap1'}
        if path == '/v1/loop/swaps': return {'swaps': copy.deepcopy(self.swap_list)}
        if path == '/v1/liquidity/params': return self.params
        if path.endswith('/terms'): return {'min_swap_amount': '1000', 'max_swap_amount': '1000000'}
        if '/quote/' in path:
            return {'swap_fee_sat': '100', 'prepay_amt_sat': '20', 'htlc_sweep_fee_sat': self.miner, 'htlc_publish_fee_sat': self.miner}
        raise AssertionError(path)


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.ops = Operations(self.api, clock=lambda: 100000)

    def plan(self, direction='out'):
        return self.ops.plan(direction, '12345', 10000, 500, 10)

    def rule(self):
        return {'scid': '12345', 'low': 30, 'high': 70, 'max_amount': 10000,
                'fee_limit': 500, 'routing_limit': 10, 'daily_budget': 1000}

    def test_out_payload_uses_exact_caps_and_numeric_scid(self):
        plan = self.plan()
        self.assertEqual(plan['reservation'], 320)
        payload = plan['payload']
        self.assertEqual(payload['outgoing_chan_set'], ['12345'])
        self.assertEqual(payload['max_miner_fee'], '200')
        self.assertEqual(payload['max_swap_fee'], '100')
        self.assertNotIn('dest', payload)  # own wallet
        self.assertEqual(self.api.posts, [])

    def test_in_payload_funds_own_wallet_and_selects_peer(self):
        plan = self.plan('in')
        self.assertFalse(plan['payload']['external_htlc'])
        self.assertEqual(plan['reservation'], 300)
        self.assertIn('last_hop', plan['payload'])

    def test_intent_survives_lost_response_and_blocks_retry(self):
        plan = self.plan()
        self.api.fail_post = True
        with self.assertRaisesRegex(LoopError, '미확인'):
            self.ops.submit(plan, 1000)
        fresh = Operations(self.api, clock=lambda: 100001)
        with self.assertRaisesRegex(LoopError, '이미 제출'):
            fresh.submit(plan, 1000)
        self.assertEqual(len(self.api.posts), 1)
        self.assertEqual(json.loads(self.api.document['data']['state.json'])['records'][0]['status'], 'SUBMITTING')

    def test_cas_conflict_prevents_submission(self):
        plan = self.plan(); self.api.conflict = True
        with self.assertRaises(LoopError): self.ops.submit(plan, 1000)
        self.assertEqual(self.api.posts, [])

    def test_unknown_submission_can_later_reconcile_without_resending(self):
        plan = self.plan(); self.api.fail_post = True
        with self.assertRaises(LoopError): self.ops.submit(plan, 1000)
        body = self.api.posts[0][1]
        self.api.swap_list = [{'id': 'recovered', 'label': body['label'], 'amt': body['amt'], 'type': 'LOOP_OUT', 'state': 'SUCCESS', 'cost_server': '100'}]
        _, journal, _ = self.ops.reconcile()
        self.assertEqual(journal['records'][0]['status'], 'SUCCESS')
        self.assertEqual(journal['records'][0]['actual_fee'], 100)
        self.assertFalse(journal['automatic']['enabled'])
        self.assertEqual(len(self.api.posts), 1)

    def test_fee_minimum_liquidity_and_invalid_quote_block(self):
        for value in ('1000', '-1'):
            self.api.miner = value
            with self.assertRaises(LoopError): self.plan()
        self.api.miner = '100'
        with self.assertRaises(LoopError): self.ops.plan('out', '12345', 500, 500)
        self.api.channel['local_balance'] = '1000'
        with self.assertRaises(LoopError): self.plan()
        self.assertFalse(self.api.posts)

    def test_post_approval_balance_change_and_expired_quote_block(self):
        plan = self.plan(); self.api.channel['active'] = False
        with self.assertRaises(LoopError): self.ops.submit(plan, 1000)
        self.api.channel['active'] = True
        self.ops.clock = lambda: 100061
        with self.assertRaisesRegex(LoopError, '만료'): self.ops.submit(plan, 1000)
        self.assertFalse(self.api.posts)

    def test_different_cluster_and_native_autoloop_block(self):
        plan = self.plan()
        self.api.binding_value['identity'] = 'other'
        with self.assertRaises(LoopError): self.ops.submit(plan, 1000)
        self.api.binding_value = plan['binding']
        self.api.params = {'autoloop': True}
        with self.assertRaisesRegex(LoopError, 'Autoloop'): self.ops.submit(plan, 1000)
        self.assertFalse(self.api.posts)

    def test_rolling_budget_includes_actual_fee_overrun(self):
        self.ops.submit(self.plan(), 1000)
        self.api.swap_list[0].update(state='SUCCESS', cost_onchain='800')
        with self.assertRaisesRegex(LoopError, '예산 부족'):
            self.ops.submit(self.plan(), 1000)
        self.assertEqual(len(self.api.posts), 1)

    def test_auto_single_attempt_and_success_stop(self):
        approval = self.ops.arm(self.rule())
        self.ops.auto_tick(approval)
        self.assertEqual(len(self.api.posts), 1)
        self.ops.auto_tick(approval)
        self.api.swap_list[0]['state'] = 'SUCCESS'
        self.ops.auto_tick(approval)
        self.assertEqual(len(self.api.posts), 1)
        self.assertFalse(json.loads(self.api.document['data']['state.json'])['automatic']['enabled'])

    def test_auto_in_and_balanced_wait(self):
        self.api.channel.update(local_balance='50000', remote_balance='50000')
        approval = self.ops.arm(self.rule())
        self.assertIn('조건 대기', self.ops.auto_tick(approval))
        self.assertFalse(self.api.posts)
        self.api.channel.update(local_balance='20000', remote_balance='80000')
        self.ops.auto_tick(approval)
        self.assertEqual(self.api.posts[0][0], '/v1/loop/in')

    def test_auto_error_disarms_and_does_not_retry(self):
        approval = self.ops.arm(self.rule()); self.api.miner = '10000'
        with self.assertRaises(LoopError): self.ops.auto_tick(approval)
        self.api.miner = '100'
        self.ops.auto_tick(approval)
        self.assertFalse(self.api.posts)

    def test_completed_plan_cannot_be_resubmitted(self):
        plan = self.plan()
        self.ops.submit(plan, 1000)
        self.api.swap_list[0]['state'] = 'SUCCESS'
        with self.assertRaisesRegex(LoopError, '이미 제출'):
            self.ops.submit(plan, 1000)
        self.assertEqual(len(self.api.posts), 1)

    def test_payload_change_after_approval_is_rejected(self):
        plan = self.plan(); plan['payload']['amt'] = '90000'
        with self.assertRaisesRegex(LoopError, '변경'):
            self.ops.submit(plan, 1000)
        self.assertFalse(self.api.posts)

    def test_late_settlement_remains_in_budget(self):
        self.ops.submit(self.plan(), 1000)
        self.ops.clock = lambda: 200000
        self.api.swap_list[0].update(state='SUCCESS', cost_onchain='800')
        with self.assertRaisesRegex(LoopError, '예산 부족'):
            self.ops.submit(self.plan(), 1000)
        self.assertEqual(len(self.api.posts), 1)

    def test_new_auto_approval_is_not_cancelled_by_old_success(self):
        self.ops.submit(self.plan(), 1000)
        self.api.swap_list[0]['state'] = 'SUCCESS'
        self.ops.reconcile()
        approval = self.ops.arm(self.rule())
        self.ops.auto_tick(approval)
        self.assertEqual(len(self.api.posts), 2)

    def test_disarm_invalidates_other_screen_approval(self):
        approval = self.ops.arm(self.rule())
        self.ops.disarm()
        self.ops.auto_tick(approval)
        self.assertFalse(self.api.posts)


if __name__ == '__main__': unittest.main()
