import datetime
import json
import pathlib
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'ops'))
from router_report import report, render, infrastructure
from router_store import write


class ReportTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = pathlib.Path(directory.name)
        self.root.chmod(0o700)
        self.current = {"identity": "node", "code": "proof_required", "ready": True, "checked_at": 1000,
                        "forwarding_proof": "verified", "proof_verified_at": 900,
                        "channels": [{"point": "tx:0", "peer": "peer", "active": True, "private": False}]}
        self.record = {"schema": "lnd-ops/testnet-reconnect/v1", "result": "pass",
                       "prepared_at": "1970-01-01T00:10:00Z", "verified_at": "1970-01-01T00:15:00Z", "elapsed_seconds": 300,
                       "before": {"node_key": "node", "pod_uid": "before", "channel_points": ["tx:0"], "peer_pubkeys": ["peer"]},
                       "after": {"node_key": "node", "pod_uid": "after", "channel_points": ["tx:0"], "peer_pubkeys": ["peer"]}}

    def test_pod_recovery_never_proves_host_reboot_or_complete(self):
        write(self.root, 'testnet-reconnect-1.json', self.record)
        result = report(self.current, {"state": "present"}, self.root, now=1000)
        self.assertEqual(result['recovery']['pod_restart']['state'], 'verified_history')
        for name in ('mac_reboot', 'windows_reboot', 'address_change'):
            self.assertEqual(result['recovery'][name]['state'], 'unverified')
        self.assertFalse(result['complete'])
        self.assertIn('Mac 재부팅  미검증', render(result))

    def test_changed_channels_keep_history_but_do_not_apply_it(self):
        write(self.root, 'testnet-reconnect-1.json', self.record)
        self.current['channels'][0]['point'] = 'replacement:0'
        result = report(self.current, {"state": "present"}, self.root, now=1000)
        self.assertEqual(result['recovery']['pod_restart']['state'], 'different_current_state')

    def test_future_or_unchanged_pod_record_does_not_prove_recovery(self):
        for field, value in (('verified_at', '2099-01-01T00:00:00Z'), ('after', self.record['before'])):
            with self.subTest(field=field):
                write(self.root, 'testnet-reconnect-1.json', self.record | {field: value})
                result = report(self.current, {"state": "present"}, self.root, now=1000)
                self.assertEqual(result['recovery']['pod_restart']['state'], 'unverified')
                self.assertEqual(result['recovery']['pod_restart']['invalid_records'], 1)

    def test_query_failure_does_not_erase_forwarding_history_or_claim_readiness(self):
        result = report(self.current | {"code": "query_error"}, {"state": "unknown"}, self.root, now=1000)
        self.assertEqual(result['readiness']['state'], 'unknown')
        self.assertEqual(result['forwarding']['state'], 'verified')

    def test_infrastructure_presence_is_separate_from_pod_and_storage_readiness(self):
        items = [{"kind": kind} for kind in ('StatefulSet', 'Pod', 'PersistentVolumeClaim', 'Service')]
        with patch('router_report.subprocess.run', return_value=Mock(stdout=json.dumps({"items": items}))) as run:
            result = infrastructure()
        self.assertEqual(result['state'], 'present')
        self.assertFalse(result['pod_ready'])
        self.assertFalse(result['pvc_bound'])
        self.assertEqual(run.call_args.args[0][:4], ['kubectl', '-n', 'lnd-testnet', 'get'])

    def test_report_requires_all_recovery_scopes_and_fresh_current_status(self):
        write(self.root, 'testnet-reconnect-1.json', self.record)
        current = self.current | {'complete': True, 'code': 'complete',
                                  'external_reachability': 'operator_attested', 'external_expires_at': 1100}
        construction = {'state': 'present', 'pod_ready': True, 'pvc_bound': True}
        history = {'state': 'verified_history'}
        with patch('router_report.historical', return_value=history), \
                patch('router_report.address_history', return_value=history):
            self.assertTrue(report(current, construction, self.root, now=1000, recovery_root=self.root)['complete'])
            for changed in ({'checked_at': 960}, {'external_expires_at': 1000}, {'ready': False}, {'code': 'query_error'}):
                with self.subTest(changed=changed):
                    self.assertFalse(report(current | changed, construction, self.root, now=1000, recovery_root=self.root)['complete'])
        with patch('router_report.historical', return_value=history), \
                patch('router_report.address_history', side_effect=[history, {'state': 'unverified'}]):
            result = report(current, construction, self.root, now=1000, recovery_root=self.root)
        self.assertFalse(result['complete'])
        self.assertIn('address_change_not_verified', result['incomplete_reasons'])


class DemoCompletionTests(unittest.TestCase):
    def setUp(self):
        self.validate = runpy.run_path(str(REPO / 'ops/verify-phase-evidence'))['validate']
        self.now = datetime.datetime(2026, 9, 27, tzinfo=datetime.timezone.utc)
        self.record = {"schema": "lnd-ops/phase9-demo/v1", "result": "pass", "checked_at": self.now.isoformat(),
                       "requested_through": 7, "completed": [{"number": n, "id": item['id']} for n, item in enumerate(
                           runpy.run_path(str(REPO / 'ops/demo'))['STAGES'], 1)]}

    def test_full_stage_record_passes_structural_validation(self):
        self.validate(self.record, 'phase9', self.now)

    def test_partial_or_reordered_demo_cannot_complete_phase(self):
        for updates in ({'requested_through': 3}, {'completed': self.record['completed'][:3]},
                        {'completed': list(reversed(self.record['completed']))}):
            with self.assertRaises(ValueError):
                self.validate(self.record | updates, 'phase9', self.now)

    def test_future_naive_and_old_times_are_rejected(self):
        for stamp in ('2099-01-01T00:00:00Z', '2026-09-27T00:00:00', '2026-09-01T00:00:00Z'):
            with self.assertRaises(ValueError):
                self.validate(self.record | {'checked_at': stamp}, 'phase9', self.now)

    def test_host_record_needs_both_platform_references_and_runtime_checks(self):
        record = {'schema': 'lnd-ops/phase8-acceptance/v1', 'result': 'pass', 'checked_at': self.now.isoformat(),
                  'hosts': {kind: {'evidence': kind + '.json', 'sha256': 'a' * 64}
                            for kind in ('mac-arm64', 'windows-wsl2-amd64')},
                  'cross_platform_runtime': 'pass', 'standard_command_surface': 'pass', 'secrets_recorded': False}
        self.validate(record, 'phase8', self.now)
        for changed in ({'hosts': {}}, {'hosts': {'mac-arm64': record['hosts']['mac-arm64']}},
                        {'cross_platform_runtime': 'pending'}, {'secrets_recorded': True}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.validate(record | changed, 'phase8', self.now)

    def test_host_acceptance_cannot_skip_router_recovery_gate(self):
        entry = runpy.run_path(str(REPO / 'ops/verify-phase-evidence'))['main']
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            record = root / 'phase8-acceptance-test.json'
            record.write_text('{}')
            record.chmod(0o600)
            import contextlib
            import io
            with patch.dict(entry.__globals__, EVIDENCE=root, validate=Mock()), \
                    patch('subprocess.run', return_value=Mock(returncode=10)) as invoke, \
                    contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(entry(['phase8']), 10)
            self.assertIn('--require-complete', invoke.call_args.args[0])
            self.assertIn('Router 운영 증거가 미완료', output.getvalue())


if __name__ == '__main__':
    unittest.main()
