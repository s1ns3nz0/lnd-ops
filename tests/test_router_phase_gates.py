import contextlib
import io
import json
import pathlib
import runpy
import unittest
from unittest.mock import Mock, patch

REPO = pathlib.Path(__file__).resolve().parents[1]


class BackupPhaseGateTests(unittest.TestCase):
    def test_missing_external_copy_prevents_backup_acceptance_record(self):
        code = runpy.run_path(str(REPO / 'ops/phase5-acceptance'))
        main = code['main']
        gates = []

        def gate(name, arguments=()):
            gates.append((name, arguments))
            if name == 'router-backup-copy':
                raise code['ManualGate']('등록한 외부 SCB 사본이 없습니다')
            return 'pass'

        def kubectl(*args, **kwargs):
            if args[:3] == ('get', 'namespace', 'lnd-regtest-recovery'):
                return Mock(returncode=1)
            if 'statefulset' in args:
                return Mock(stdout=json.dumps({'spec': {'replicas': 1}}))
            if 'pvc' in args:
                return Mock(stdout='pvc')
            return Mock(stdout=json.dumps({'metadata': {}}))

        latest = Mock(side_effect=[(pathlib.Path('recovery.json'), {'original_pvc_uid': 'pvc'}),
                                   (pathlib.Path('alert.json'), {'alertmanager_observed': True, 'restored_current_metric': True})])
        save = Mock()
        with patch.dict(main.__globals__, command=Mock(return_value=Mock(stdout='')), latest=latest,
                        kubectl=kubectl, run_gate=gate, write_result=save), contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(main([]), 10)
        self.assertIn(('router-backup-copy', ['--status', '--json']), gates)
        self.assertIn('외부 SCB 사본', output.getvalue())
        save.assert_not_called()

    def test_external_backup_gate_uses_human_message_instead_of_raw_json(self):
        code = runpy.run_path(str(REPO / 'ops/phase5-acceptance'))
        gate = code['run_gate']
        response = Mock(returncode=10, stderr='', stdout=json.dumps({'state': 'missing', 'message': '외부 사본 없음'}))
        with patch.dict(gate.__globals__, command=Mock(return_value=response)), self.assertRaisesRegex(code['ManualGate'], '^외부 사본 없음$'):
            gate('router-backup-copy', ['--status', '--json'])


if __name__ == '__main__':
    unittest.main()
