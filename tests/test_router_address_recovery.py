import copy
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'ops'))
from router_address_recovery import prepare, verify, cancel, verify_pair, historical
from router_store import read


def observation(issued=100, endpoint='8.8.8.8:9735', guest='172.20.1.2', kind='windows'):
    key = '02' + '1' * 64
    request = {'schema': 'lnd-ops/router-p2p-request/v1', 'nonce': str(issued).zfill(64),
               'identity': key, 'endpoint': endpoint, 'issued_at': issued, 'expires_at': issued + 600}
    result = {'schema': 'lnd-ops/router-p2p-observation/v1', 'request': request,
              'started_at': issued + 1, 'verified_at': issued + 2, 'remote_key': key,
              'observer_key': '03' + '2' * 64, 'local_address': '192.168.1.2:1111',
              'authenticated_handshake': True, 'lightning_init_received': True,
              'network_origin': 'operator-attested-external'}
    return {'host': {'kind': kind, 'identity_sha256': 'a' * 64, 'boot_id': 'boot', 'boot_started_at': 50},
            'cluster_uid': 'cluster', 'node_uid': 'node', 'guest_boot_id': 'guest',
            'wallet': key, 'pvc_uid': 'pvc', 'pv_uid': 'pv', 'ready': True,
            'channels': [{'point': 'tx:0', 'id': '1', 'peer': 'peer1'}, {'point': 'tx:1', 'id': '2', 'peer': 'peer2'}],
            'observed_at': issued + 100, 'endpoint': endpoint, 'guest_addresses': [guest],
            'external': {'schema': 'lnd-ops/router-p2p-receipt/v1', 'observation': result,
                         'imported_at': issued + 3, 'provenance': 'operator-controlled-unsigned'}}


class AddressRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = pathlib.Path(temp.name) / 'router'
        self.before = observation()
        self.after = observation(800, guest='172.21.1.2')

    def test_guest_address_change_preserves_public_endpoint_and_wallet(self):
        result = verify_pair(self.before, self.after)
        self.assertEqual(result['changes'], ['guest_address'])
        self.assertEqual(result['elapsed_seconds'], 700)
        self.assertEqual(result['external_provenance'], 'operator-controlled-unsigned')

    def test_public_address_change_is_distinguished_from_guest_change(self):
        result = verify_pair(observation(kind='mac'), observation(800, endpoint='8.8.4.4:9735', kind='mac'))
        self.assertEqual(result['changes'], ['public_endpoint'])

    def test_unchanged_address_is_not_recovery(self):
        with self.assertRaisesRegex(ValueError, '바뀌지'):
            verify_pair(self.before, observation(800))

    def test_old_or_expired_external_observation_cannot_prove_recovery(self):
        for changed in (self.before['external'], self.after['external'] | {'imported_at': 9999}):
            with self.assertRaises(ValueError):
                verify_pair(self.before, self.after | {'external': changed})
        after = observation(110, guest='172.21.1.2')
        with self.assertRaisesRegex(ValueError, '새 외부'):
            verify_pair(self.before, after)

    def test_storage_channels_and_physical_host_must_be_preserved(self):
        for field in ('cluster_uid', 'node_uid', 'wallet', 'pvc_uid', 'pv_uid'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_pair(self.before, self.after | {field: 'changed'})
        after = copy.deepcopy(self.after)
        after['channels'][0]['point'] = 'new:0'
        with self.assertRaises(ValueError):
            verify_pair(self.before, after)
        after = copy.deepcopy(self.after)
        after['host']['identity_sha256'] = 'b' * 64
        with self.assertRaises(ValueError):
            verify_pair(self.before, after)

    def test_prepare_and_failure_preserve_baseline_then_success_clears(self):
        prepare(self.root, lambda: self.before)
        observe = Mock(return_value=self.after)
        with self.assertRaises(ValueError):
            prepare(self.root, observe)
        observe.assert_not_called()
        with self.assertRaises(ValueError):
            verify(self.root, lambda: observation(800))
        self.assertIsNotNone(read(self.root, 'address-recovery-pending.json'))
        result = verify(self.root, observe)
        self.assertIsNone(read(self.root, 'address-recovery-pending.json'))
        self.assertEqual(read(self.root, 'address-recovery-windows.json'), result)
        cancel(self.root)
        self.assertEqual(read(self.root, 'address-recovery-windows.json'), result)

    def test_history_revalidates_without_claiming_current_external_reachability(self):
        prepare(self.root, lambda: self.before)
        verify(self.root, lambda: self.after)
        current = {'identity': self.after['wallet'], 'code': 'ready',
                   'channels': [c | {'active': True, 'private': False} for c in self.after['channels']]}
        result = historical(self.root, 'windows', current, now=2000)
        self.assertEqual(result['state'], 'verified_history')
        self.assertEqual(historical(self.root, 'windows', current | {'identity': 'other'}, now=2000)['state'], 'different_current_state')
        self.assertEqual(historical(self.root, 'windows', current | {'code': 'query_error'}, now=2000)['state'], 'current_unavailable')
        self.assertEqual(historical(self.root, 'windows', current, now=800)['state'], 'invalid_record')


if __name__ == '__main__':
    unittest.main()
