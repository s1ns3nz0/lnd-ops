import copy
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'ops'))
from router_observation import CONFIRM, issue, import_result, current, public_endpoint
from router_store import read

KEY = '02' + '1' * 64
OTHER = '03' + '2' * 64
ENDPOINT = '8.8.8.8:9735'  # Fixture only. No test contacts this address.


class ObservationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name) / 'router'
        self.info = {'testnet': True, 'synced_to_chain': True, 'identity_pubkey': KEY,
                     'uris': [f'{KEY}@{ENDPOINT}']}
        self.request = issue(self.root, self.info, ENDPOINT, now=100)
        self.result = {'schema': 'lnd-ops/router-p2p-observation/v1', 'request': self.request,
                       'started_at': 101, 'verified_at': 103, 'observer_key': OTHER,
                       'local_address': '192.168.1.2:12345', 'remote_key': KEY,
                       'authenticated_handshake': True, 'lightning_init_received': True,
                       'network_origin': 'operator-attested-external'}

    def receive(self, result=None, info=None, now=104):
        return import_result(self.root, result or self.result, info or self.info, CONFIRM, now=now)

    def test_idempotent_issue_and_import_preserve_request(self):
        self.assertEqual(issue(self.root, self.info, ENDPOINT, now=105), self.request)
        record = self.receive()
        self.assertEqual(record, read(self.root, 'p2p-observation.json'))
        self.assertEqual(self.receive(), record)
        self.assertTrue(current(record, self.info, now=105))
        self.assertFalse(current(record, self.info, now=700))
        self.assertEqual(record['provenance'], 'operator-controlled-unsigned')

    def test_forged_or_replayed_request_is_rejected(self):
        for field, value in [('nonce', '0' * 64), ('endpoint', '8.8.4.4:9735'),
                             ('identity', OTHER), ('issued_at', 99)]:
            changed = copy.deepcopy(self.result)
            changed['request'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.receive(changed)
        self.assertIsNone(read(self.root, 'p2p-observation.json'))

    def test_expired_request_cannot_be_revived_by_import(self):
        with self.assertRaises(ValueError):
            self.receive(now=700)
        replacement = issue(self.root, self.info, ENDPOINT, now=700)
        self.assertNotEqual(replacement['nonce'], self.request['nonce'])
        with self.assertRaises(ValueError):
            self.receive(now=701)

    def test_wallet_or_advertised_address_change_invalidates_result(self):
        record = self.receive()
        for changed in (self.info | {'identity_pubkey': OTHER}, self.info | {'uris': []},
                        self.info | {'testnet': False}):
            with self.assertRaises((ValueError, RuntimeError)):
                self.receive(info=changed)
            self.assertFalse(current(record, changed, now=105))

    def test_no_unapproved_import_and_protocol_claim_must_be_true(self):
        with self.assertRaises(ValueError):
            import_result(self.root, self.result, self.info, '', now=104)
        for field, value in [('authenticated_handshake', False), ('lightning_init_received', 1),
                             ('network_origin', 'local'), ('remote_key', OTHER),
                             ('observer_key', KEY), ('local_address', '\n')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.receive(self.result | {field: value})

    def test_clock_skew_long_probe_and_malformed_times_rejected(self):
        for fields in ({'started_at': 99}, {'verified_at': 105}, {'started_at': True},
                       {'verified_at': 102.5}, {'started_at': 104},
                       {'started_at': 101, 'verified_at': 117}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.receive(self.result | fields)

    def test_target_must_be_public_numeric_advertised_9735(self):
        for endpoint in ('localhost:9735', '127.0.0.1:9735', '10.1.1.1:9735',
                         '100.64.1.1:9735', '203.0.113.1:9735', '8.8.8.8:22',
                         '[::1]:9735', '[2001:db8::1]:9735', '224.0.0.1:9735', '192.0.0.9:9735'):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                public_endpoint(endpoint)
        with self.assertRaises(ValueError):
            issue(self.root, self.info, '8.8.4.4:9735', now=105)
        changed = self.info | {'uris': [f'{KEY}@8.8.4.4:9735']}
        with self.assertRaisesRegex(ValueError, '만료'):
            issue(self.root, changed, '8.8.4.4:9735', now=105)

    def test_malformed_record_is_not_current_evidence(self):
        for record in (None, [], {}, {'schema': 'lnd-ops/router-p2p-receipt/v1',
                                  'provenance': 'operator-controlled-unsigned'}):
            self.assertFalse(current(record, self.info, now=104))


if __name__ == '__main__':
    unittest.main()
