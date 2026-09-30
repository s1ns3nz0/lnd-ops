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
        for word in ('none', 'present', 'elevated', 'rejected_total', 'rejected_baseline_per_15m'):
            self.assertIn(f'`{word}`', FUNNEL_DOC)
        for result in gw.MINT_RESULTS:
            self.assertIn(result, FUNNEL_DOC)

    def test_every_failure_reason_is_in_a_playbook(self):
        for reason in gw.FAILURE_REASONS:
            self.assertTrue(f'`{reason}`' in ORDER_DOC or f'`{reason}`' in FUNNEL_DOC, reason)

    def test_funnel_playbook_pins_components_rails_and_thresholds(self):
        for name in ('l402-aperture', 'payment-aperture-services', 'lnd-merchant', 'paid-scan-api', 'x402-facilitator'):
            self.assertIn(f'- `{name}`:', FUNNEL_DOC)
        for text in ('These are the only components on the L402 path.',
                     'The only alternative payment rail is x402. There is no card, PayPal or other method.',
                     'The playbook sets no time threshold for disabling L402',
                     'do not look for a separate pricer service'):
            self.assertIn(text, FUNNEL_DOC)
        self.assertIn('payment rails are exactly l402 and x402', ORDER_DOC)

    def test_system_message_forbids_unsourced_names_and_numbers(self):
        tpl = (REPO / 'charts/agent/templates/_helpers.tpl').read_text()
        self.assertIn('Name only components, services, payment methods and numbers (thresholds, durations) that appear in tool output or the playbook; if something is not there, say it is unknown instead of guessing.', tpl)

    def test_change_fields_and_rollback_are_in_playbooks(self):
        for field in ('recent_changes', 'revision', 'last_change', 'images'):
            self.assertTrue(f'`{field}`' in ORDER_DOC or f'`{field}`' in FUNNEL_DOC, field)
        for doc in (ORDER_DOC, FUNNEL_DOC):
            mitigate = doc.split('## 2. Mitigate first')[1].split('## 3.')[0]
            self.assertIn('kubectl rollout undo deploy/<name>', mitigate)
            self.assertIn('`recent_changes`', mitigate)
            self.assertIn('kubectl rollout history', doc.split('## 3. Triage')[1].split('## 4.')[0])
            self.assertIn('rollout undo', doc.split('## 5. Fix and verify')[1].split('## 6.')[0])
        tpl = (REPO / 'charts/agent/templates/_helpers.tpl').read_text()
        self.assertIn('Check recent_changes first; a rollout shortly before the symptom is the leading hypothesis', tpl)


if __name__ == '__main__':
    unittest.main()
