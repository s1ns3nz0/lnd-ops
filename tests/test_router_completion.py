import contextlib
import copy
import importlib.machinery
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'ops'))
verify = importlib.machinery.SourceFileLoader('router_completion_verifier', str(REPO / 'ops/verify-router')).load_module()
cli = importlib.machinery.SourceFileLoader('router_observation_cli', str(REPO / 'ops/router-observation')).load_module()
from router_observation import CONFIRM, issue, import_result
from router_rpc import GraphEdgeMissing, RPCError
from test_router_model import channel


P2P_SERVICE = {'spec': {'type': 'NodePort', 'selector': {'app.kubernetes.io/name': 'lnd-0'},
                       'ports': [{'port': 9735, 'targetPort': 9735, 'nodePort': 30973, 'protocol': 'TCP'}]}}


class RouterCompletionTests(unittest.TestCase):
    def test_invalid_p2p_service_cannot_complete_even_with_old_proofs(self):
        cases = []
        for field, value in (('protocol', 'UDP'), ('targetPort', 10009), ('targetPort', 'rpc'),
                             ('nodePort', 30009), ('port', 10009)):
            service = copy.deepcopy(P2P_SERVICE)
            service['spec']['ports'][0][field] = value
            cases.append(service)
        for field, value in (('type', 'LoadBalancer'), ('selector', {}),
                             ('selector', {'app.kubernetes.io/name': 'lnd-1'})):
            service = copy.deepcopy(P2P_SERVICE)
            service['spec'][field] = value
            cases.append(service)
        extra = copy.deepcopy(P2P_SERVICE)
        extra['spec']['ports'].append({'port': 10009, 'targetPort': 10009, 'nodePort': 30009})
        cases.append(extra)
        for service in cases:
            with self.subTest(service=service), \
                 patch.object(verify.subprocess, 'run', return_value=Mock(returncode=0, stdout=json.dumps(service))), \
                 patch.object(verify, 'call') as rpc, patch.object(verify, 'read') as proof:
                result = verify.snapshot()
            self.assertFalse(result['complete'])
            self.assertEqual(result['code'], 'query_error')
            rpc.assert_not_called()
            proof.assert_not_called()

    def test_kubernetes_tcp_and_target_port_defaults_are_allowed(self):
        service = copy.deepcopy(P2P_SERVICE)
        del service['spec']['ports'][0]['protocol']
        del service['spec']['ports'][0]['targetPort']
        verify.validate_p2p_service(service)

    def test_missing_graph_edge_preserves_channels_and_recovers_on_next_read(self):
        info = self.info | {'synced_to_graph': True}
        channels = [channel(1), channel(2)]
        policy = {'fee_base_msat': '1000', 'fee_rate_milli_msat': '500', 'min_htlc': '1',
                  'max_htlc_msat': '90000000', 'disabled': False}
        graph = {'node1_pub': self.key, 'node1_policy': policy, 'node2_policy': policy}
        missing = True

        def rpc(command, *args):
            if command == 'listchannels':
                return {'channels': channels}
            if command == 'pendingchannels':
                return {}
            if command == 'listpeers':
                return {'peers': [{'pub_key': 'peer1'}, {'pub_key': 'peer2'}]}
            if command == 'getchaninfo':
                if missing and args == ('--chan_id=1',):
                    raise GraphEdgeMissing('missing edge')
                return graph
            raise AssertionError(command)

        with patch.object(verify, 'target', return_value=None):
            result = verify.readiness(rpc=rpc, info=info)
            self.assertEqual(result['code'], 'graph_pending')
            self.assertFalse(result['ready'])
            self.assertEqual(len(result['channels']), 2)
            missing = False
            self.assertTrue(verify.readiness(rpc=rpc, info=info)['ready'])

    def test_graph_rpc_failure_is_not_swallowed_as_missing_data(self):
        rpc = Mock(side_effect=[{'channels': [channel(1)]}, {}, {'peers': []}, RPCError('permission denied')])
        with patch.object(verify, 'target', return_value=None), \
             patch.object(verify, 'assess', return_value={'code': 'graph_pending'}), \
             self.assertRaisesRegex(RPCError, 'permission denied'):
            verify.readiness(rpc=rpc, info=self.info)

    def test_graph_pending_precheck_still_fetches_graph_and_reassesses(self):
        snapshots = [{'code': 'graph_pending', 'ready': False}, {'code': 'ready', 'ready': True}]
        channel = {'scid': '123', 'active': True, 'private': False}
        rpc = Mock(side_effect=[{'channels': [channel]}, {}, {'peers': []},
                               {'node1_pub': 'node', 'node1_policy': {'known': True}, 'node2_policy': None}])
        with patch.object(verify, 'target', return_value={}), patch.object(verify, 'assess', side_effect=snapshots) as assess:
            result = verify.readiness(rpc=rpc, info={'identity_pubkey': 'node'})
        self.assertTrue(result['ready'])
        self.assertEqual(rpc.call_args.args, ('getchaninfo', '--chan_id=123'))
        self.assertEqual(assess.call_args.args[4], {'123': {'own': {'known': True}, 'remote': None}})

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = pathlib.Path(temp.name) / 'router'
        self.key = '02' + '1' * 64
        self.info = {'testnet': True, 'synced_to_chain': True, 'identity_pubkey': self.key,
                     'uris': [self.key + '@8.8.8.8:9735']}
        request = issue(self.root, self.info, '8.8.8.8:9735', now=100)
        observation = {'schema': 'lnd-ops/router-p2p-observation/v1', 'request': request,
                       'started_at': 101, 'verified_at': 102, 'remote_key': self.key,
                       'observer_key': '03' + '2' * 64, 'local_address': '192.168.1.2:1111',
                       'authenticated_handshake': True, 'lightning_init_received': True,
                       'network_origin': 'operator-attested-external'}
        self.receipt = import_result(self.root, observation, self.info, CONFIRM, now=103)

    def snapshot(self, ready=True, forwarding=True, receipt=True, now=104, observed=False):
        service = Mock(returncode=0, stdout=json.dumps(P2P_SERVICE))
        with patch.object(verify.subprocess, 'run', return_value=service), \
             patch.object(verify, 'call', return_value=self.info), \
             patch.object(verify, 'readiness', return_value={'ready': ready, 'code': 'ready' if ready else 'syncing',
                                                           'identity': self.key, 'channels': [], 'message': 'waiting'}), \
             patch.object(verify, 'read', side_effect=[{'verified_at': 90}, self.receipt if receipt else None]), \
             patch.object(verify, 'current_evidence', return_value=forwarding), \
             patch.object(verify, 'observe', return_value={'forwarding_observed_count': int(observed), 'forwarding_observed_at': 99 if observed else None}), \
             patch('router_observation.time.time', return_value=now):
            return verify.snapshot()

    def test_completion_requires_readiness_forwarding_and_fresh_external_result(self):
        for ready, forwarding, receipt in ((False, True, True), (True, False, True), (True, True, False)):
            with self.subTest(ready=ready, forwarding=forwarding, receipt=receipt):
                self.assertFalse(self.snapshot(ready, forwarding, receipt)['complete'])
        result = self.snapshot()
        self.assertTrue(result['complete'])
        self.assertEqual(result['external_reachability'], 'operator_attested')
        self.assertEqual(result['external_provenance'], 'operator-controlled-unsigned')

    def test_local_observation_is_distinct_from_controlled_proof_and_requires_external_check(self):
        result = self.snapshot(forwarding=False, observed=True, receipt=False)
        self.assertEqual(result['forwarding_proof'], 'observed')
        self.assertEqual(result['forwarding_provenance'], 'local-lnd-history')
        self.assertFalse(result['complete'])
        self.assertEqual(result['code'], 'external_required')
        self.assertTrue(self.snapshot(forwarding=False, observed=True)['complete'])

    def test_expiry_and_address_change_reopen_external_work(self):
        result = self.snapshot(now=700)
        self.assertFalse(result['complete'])
        self.assertEqual(result['code'], 'external_required')
        self.info['uris'] = []
        self.assertFalse(self.snapshot()['complete'])

    def test_forwarding_is_requested_before_external_probe(self):
        self.assertEqual(self.snapshot(forwarding=False, receipt=False)['code'], 'proof_required')

    def test_interactive_request_displays_saved_file_without_connection(self):
        with patch.object(cli.sys.stdin, 'isatty', return_value=True), \
             patch('builtins.input', side_effect=['1', '1']), \
             patch('router_observation.time.time', return_value=104), \
             patch.object(cli, 'call') as rpc, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.interactive(self.root, self.info), 10)
        rpc.assert_not_called()
        self.assertIn(str(self.root / 'p2p-request.json'), output.getvalue())

    def test_interactive_cancel_never_imports(self):
        with patch.object(cli.sys.stdin, 'isatty', return_value=True), \
             patch('builtins.input', side_effect=['2', '/unused', 'no']), \
             patch.object(cli, 'import_result') as receive, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.interactive(self.root, self.info), 10)
        receive.assert_not_called()


if __name__ == '__main__':
    unittest.main()
