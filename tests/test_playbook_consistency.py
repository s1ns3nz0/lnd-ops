"""Every value the diagnostics code can emit must be explained in the playbooks."""
import copy
import importlib.util
import pathlib
import unittest

REPO = pathlib.Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location('psd', REPO / 'agent/paid_scan_diagnostics.py')
gw = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gw)
ORDER_DOC = (REPO / 'docs/playbooks/opencti-paid-order-stuck.md').read_text()
FUNNEL_DOC = (REPO / 'docs/playbooks/opencti-l402-funnel.md').read_text()
T, O = '11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222'
BASE = {'schema_version': 1, 'source': 'tenant_database', 'tenant_id': T, 'observed_at': '2026-09-27T10:00:00Z',
        'order': {'id': O, 'state': 'paid'},
        'payment': {'rail': 'l402', 'event_recorded': True, 'receipt_commit_state': 'committed', 'challenge': {'state': 'settled'}},
        'scan': {'state': 'queued', 'result_available_at': None},
        'dispatch': {'state': 'pending', 'updated_at': '2026-09-27T09:58:00Z'}}
NOW = gw.timestamp('2026-09-27T10:00:00Z')


def variant(**edits):
    data = copy.deepcopy(BASE)
    for path, value in edits.items():
        section, key = path.split('__')
        if key == 'whole':
            data[section] = value
        else:
            data[section][key] = value
    return data


CASES = [
    variant(order__state='payment_pending'), variant(payment__event_recorded=False),
    variant(payment__receipt_commit_state='pending'), variant(scan__whole=None, dispatch__whole=None),
    variant(scan__state='failed'), variant(scan__whole={'state': 'completed', 'result_available_at': None}),
    variant(scan__whole={'state': 'completed', 'result_available_at': '2026-09-27T09:59:00Z'}),
    variant(scan__state='running'), variant(dispatch__state='registered'), variant(dispatch__state='dispatched'),
    variant(dispatch__state='pending'), variant(scan__whole={'state': 'queued', 'result_available_at': '2026-09-27T09:59:00Z'}),
]


class Consistency(unittest.TestCase):
    def outcomes(self):
        out = [gw.diagnose({'tenant_id': T, 'order_id': O}, fetch=lambda *a, d=d: d, now=NOW) for d in CASES]
        out.append(gw.diagnose({'tenant_id': T, 'order_id': O}, fetch=lambda *a: {}, now=NOW))
        return out

    def test_every_stage_and_next_check_is_in_order_playbook(self):
        out = self.outcomes()
        stages = {r['stage'] for r in out if r['status'] == 'observed'}
        self.assertGreaterEqual(len(stages), 10)
        for stage in stages:
            self.assertIn(f'`{stage}`', ORDER_DOC)
        for check in {r['next_check'].split(';')[0] for r in out}:
            self.assertIn(check, ORDER_DOC)

    def test_funnel_verdicts_and_signals_are_in_funnel_playbook(self):
        for word in ('incident', 'inconclusive', 'no_l402_traffic', 'healthy', 'requests_without_invoice', 'secret_store_error'):
            self.assertIn(f'`{word}`', FUNNEL_DOC)
        for result in gw.MINT_RESULTS:
            self.assertIn(result, FUNNEL_DOC)

    def test_every_failure_reason_is_in_a_playbook(self):
        for reason in gw.FAILURE_REASONS:
            self.assertTrue(f'`{reason}`' in ORDER_DOC or f'`{reason}`' in FUNNEL_DOC, reason)


if __name__ == '__main__':
    unittest.main()
