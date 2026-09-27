import copy
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'ops'))
from router_recovery import prepare, verify, cancel, verify_pair, historical
from router_store import read, write


def observation(boot='before', started=100, observed=200, kind='mac'):
    return {'host': {'kind': kind, 'identity_sha256': 'a' * 64, 'boot_id': boot, 'boot_started_at': started},
            'cluster_uid': 'cluster', 'node_uid': 'node', 'guest_boot_id': boot,
            'wallet': 'wallet', 'pvc_uid': 'pvc', 'pv_uid': 'pv', 'ready': True,
            'channels': [{'point': 'tx:0', 'id': '1', 'peer': 'peer1'}, {'point': 'tx:1', 'id': '2', 'peer': 'peer2'}],
            'observed_at': observed}


class HostRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name) / 'router'
        self.before = observation()
        self.after = observation('after', 250, 300)

    def test_real_host_transition_preserves_wallet_storage_channels(self):
        for kind in ('mac', 'windows'):
            before = observation(kind=kind)
            after = observation('after', 250, 300, kind)
            result = verify_pair(before, after)
            self.assertEqual(result['kind'], kind)
            self.assertEqual(result['elapsed_seconds'], 100)
            self.assertEqual(result['unlock_mode'], 'manual')
            self.assertFalse(result['external_p2p_verified'])

    def test_pod_or_guest_restart_without_host_boot_change_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '실제 호스트 재부팅'):
            verify_pair(self.before, observation(observed=300))

    def test_changed_boot_before_baseline_cannot_prove_new_reboot(self):
        with self.assertRaises(ValueError):
            verify_pair(self.before, observation('after', 150, 300))

    def test_remote_cluster_that_did_not_reboot_is_not_host_recovery(self):
        self.after['guest_boot_id'] = self.before['guest_boot_id']
        with self.assertRaisesRegex(ValueError, 'guest'):
            verify_pair(self.before, self.after)

    def test_wallet_cluster_or_volume_replacement_is_rejected(self):
        for field in ('wallet', 'cluster_uid', 'pvc_uid', 'pv_uid', 'channels'):
            after = copy.deepcopy(self.after)
            after[field] = 'replacement' if field != 'channels' else after[field][:1]
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_pair(self.before, after)

    def test_different_physical_host_is_rejected(self):
        self.after['host']['identity_sha256'] = 'b' * 64
        with self.assertRaisesRegex(ValueError, '다른 호스트'):
            verify_pair(self.before, self.after)

    def test_prepare_does_not_overwrite_pending_observation(self):
        prepare(self.root, lambda: self.before)
        observe = Mock(return_value=self.after)
        with self.assertRaises(ValueError):
            prepare(self.root, observe)
        observe.assert_not_called()
        self.assertEqual(read(self.root, 'host-recovery-pending.json')['before'], self.before)

    def test_failed_verification_keeps_baseline_and_success_clears_it(self):
        prepare(self.root, lambda: self.before)
        with self.assertRaises(ValueError):
            verify(self.root, lambda: observation(observed=300))
        self.assertIsNotNone(read(self.root, 'host-recovery-pending.json'))
        result = verify(self.root, lambda: self.after)
        self.assertEqual(read(self.root, 'host-recovery-mac.json'), result)
        self.assertIsNone(read(self.root, 'host-recovery-pending.json'))

    def test_cancel_preserves_success_evidence(self):
        prepare(self.root, lambda: self.before)
        verify(self.root, lambda: self.after)
        saved = read(self.root, 'host-recovery-mac.json')
        prepare(self.root, lambda: self.after)
        cancel(self.root)
        self.assertIsNone(read(self.root, 'host-recovery-pending.json'))
        self.assertEqual(read(self.root, 'host-recovery-mac.json'), saved)

    def test_historical_check_revalidates_records_and_current_binding(self):
        write(self.root, 'host-recovery-mac.json', verify_pair(self.before, self.after))
        current = {'identity': 'wallet', 'code': 'proof_required',
                   'channels': [c | {'active': True, 'private': False} for c in self.after['channels']]}
        self.assertEqual(historical(self.root, 'mac', current, 400)['state'], 'verified_history')
        self.assertEqual(historical(self.root, 'mac', current | {'identity': 'different'}, 400)['state'], 'different_current_state')
        self.assertEqual(historical(self.root, 'mac', current, 299)['state'], 'invalid_record')
        self.after['pvc_uid'] = 'replacement'
        write(self.root, 'host-recovery-mac.json', {'schema': 'lnd-ops/router-host-recovery/v1', 'result': 'pass',
              'kind': 'mac', 'before': self.before, 'after': self.after})
        self.assertEqual(historical(self.root, 'mac', current, 400)['state'], 'invalid_record')


if __name__ == '__main__':
    unittest.main()
