import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ops'))
import flux_ops as f


def resource(generation=2, ready=True):
    return {'metadata': {'name': 'fixture', 'generation': generation}, 'spec': {},
            'status': {'conditions': [{'type': 'Ready', 'status': 'True' if ready else 'False', 'observedGeneration': generation}]}}


class FluxTests(unittest.TestCase):
    def test_readiness_rejects_old_generation_suspension_and_reconciling(self):
        good = resource()
        self.assertTrue(f.ready(good))
        for changed in ('generation', 'suspend', 'reconciling'):
            obj = copy.deepcopy(good)
            if changed == 'generation': obj['metadata']['generation'] += 1
            elif changed == 'suspend': obj['spec']['suspend'] = True
            else: obj['status']['conditions'].append({'type': 'Reconciling', 'status': 'True'})
            self.assertFalse(f.ready(obj))

    def test_no_ready_or_missing_never_passes(self):
        self.assertFalse(f.ready(None))
        self.assertFalse(f.ready({'metadata': {'generation': 1}, 'status': {}}))

    def test_prepare_does_not_mutate_cluster_or_publish_git(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(f, 'REPO', Path(tmp)), \
                patch.object(f, 'context_uid', return_value='cluster-1'), patch.object(f, 'apply') as apply, \
                patch.object(f, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            f.prepare('wsl', 'https://example.org/repo.git', 'main')
            root = f.directory('wsl')
            bootstrap = json.loads((root / 'bootstrap.json').read_text())
            self.assertFalse(bootstrap['items'][1]['spec']['prune'])
            self.assertEqual(bootstrap['items'][1]['spec']['deletionPolicy'], 'Orphan')
            hr = json.loads((root / 'workloads/probe.json').read_text())
            self.assertEqual(hr['spec']['upgrade']['strategy']['name'], 'RetryOnFailure')
            self.assertFalse((root / 'workloads/lnd.json').exists())
            with self.assertRaises(ValueError): f.prepare('wsl', 'https://example.org/repo.git', 'main')
        apply.assert_not_called()
        self.assertTrue(all(c.args[:2] == ('git', 'check-ref-format') for c in run.call_args_list))

    def test_prepare_rejects_credentials_and_unsafe_urls(self):
        for url in ('https://token@example.org/x', 'https://example.org/x?token=secret', 'ssh://git:pw@example.org/x', 'http://example.org/x', 'file:///tmp/repo'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                f.prepare('wsl', url, 'main')

    def test_cluster_binding_refuses_mac_wsl_mixup(self):
        with patch.object(f, 'config', return_value={'clusterUID': 'wsl'}), patch.object(f, 'context_uid', return_value='mac'):
            with self.assertRaises(f.Pending): f.bound_config('wsl')

    def test_guard_blocks_owner_annotation_even_without_flux_crds(self):
        ns = {'metadata': {'annotations': {f.OWNER: 'wsl'}}}
        with patch.object(f, 'get', return_value=ns) as get:
            with self.assertRaisesRegex(f.Pending, '직접 Helm'): f.guard('lnd-testnet', 'lnd-ops')
        self.assertEqual(get.call_count, 1)

    def test_guard_blocks_suspended_release_in_different_storage_namespace(self):
        hr = f.helmrelease('lnd-ops', './chart', 'lnd-testnet', {}, suspended=True)
        hr['spec']['storageNamespace'] = 'helm-storage'
        with patch.object(f, 'get', side_effect=[None, {'metadata': {}}]), \
                patch.object(f, 'read_json', return_value={'items': [hr]}):
            with self.assertRaises(f.Pending): f.guard('lnd-testnet', 'lnd-ops')

    def test_guard_allows_unmanaged_and_fails_closed_on_api_error(self):
        with patch.object(f, 'get', return_value=None): f.guard('lnd-testnet', 'lnd-ops')
        with patch.object(f, 'get', side_effect=f.Pending('API unavailable')):
            with self.assertRaises(f.Pending): f.guard('lnd-testnet', 'lnd-ops')

    def test_same_wallet_detects_replaced_pvc_identity_and_channel(self):
        original = {'pvcs': {'pvc': 'uid'}, 'nodes': {'lnd-0': {'pubkey': 'abc', 'channels': ['tx:0'], 'active': ['tx:0']}}}
        f.same_wallet(original, copy.deepcopy(original))
        for field in ('pvcs', 'nodes'):
            changed = copy.deepcopy(original); changed[field] = {}
            with self.assertRaises(f.Pending): f.same_wallet(original, changed)

    def test_secret_export_rejects_nested_credentials(self):
        f.reject_secrets({'bitcoin': {'rpcPassword': 'local-regtest-only'}, 'loop': {'credentialsSecret': 'name-only'}})
        for obj in ({'bitcoin': {'rpcPassword': 'custom-secret'}}, {'x': [{'token': 'secret'}]}, {'seed': 'words'}):
            with self.assertRaises(ValueError): f.reject_secrets(obj)

    def test_completion_requires_actual_latest_chart_attempt(self):
        hr = resource(); hr['spec']['chart'] = {'spec': {'sourceRef': {'kind': 'GitRepository', 'name': f.NAME}}}; hr['status'].update({'helmChart': 'flux-system/chart', 'lastAttemptedRevision': '0.1.0+old'})
        hc = resource(); hc['status'].update({'observedSourceArtifactRevision': 'main@sha1:new', 'artifact': {'revision': '0.1.0+new'}})
        with patch.object(f, 'get', side_effect=[hr, hc]):
            with self.assertRaises(f.Pending): f.release_state('name', 'main@sha1:new')
        hr['status']['lastAttemptedRevision'] = '0.1.0+new'
        with patch.object(f, 'get', side_effect=[hr, hc]):
            self.assertEqual(f.release_state('name', 'main@sha1:new'), hr)

    def test_install_checksum_failure_happens_before_any_apply(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(f, 'REPO', Path(tmp)), patch.object(f, 'bound_config'), patch.object(f, 'run') as run:
            path = Path(tmp) / 'charts/flux'; path.mkdir(parents=True)
            (path / 'install.yaml').write_text('tampered')
            f.write(path / 'lock.json', {'file': 'install.yaml', 'sha256': '0' * 64})
            with self.assertRaises(ValueError): f.install('wsl')
        run.assert_not_called()

    def test_failed_probe_requires_own_failure_and_current_generation(self):
        c = {'clusterUID': 'uid'}
        hr = resource(ready=False)
        hr['spec']['values'] = {'marker': 'failure', 'fail': True}
        hr['status']['conditions'][0]['message'] = 'unrelated outage'
        with patch.object(f, 'bound_config', return_value=c), patch.object(f, 'source_state', return_value='new'), \
                patch.object(f, 'release_state', return_value=hr), patch.object(f, 'cm_record') as write:
            with self.assertRaises(f.Pending): f.capture_probe('wsl', 'failure')
        write.assert_not_called()

    def test_completed_exercise_needs_three_distinct_revisions(self):
        c = {'clusterUID': 'uid'}
        proof = {'clusterUID': 'uid', 'configDigest': f.digest(c), 'stages': dict.fromkeys(('baseline', 'failure', 'recovery'), 'same')}
        with patch.object(f, 'record', return_value=proof):
            with self.assertRaises(f.Pending): f.require_exercise(c)

    def test_multi_document_manifest_comparison_handles_kubectl_json_stream(self):
        objects = [{'kind': 'Service', 'metadata': {'name': 'service'}}, {'kind': 'ConfigMap', 'metadata': {'name': 'config'}}]
        output = '\n'.join(json.dumps(x) for x in objects)
        with patch.object(f, 'run', return_value=subprocess.CompletedProcess([], 0, output, '')):
            self.assertEqual([x['kind'] for x in f.normalized_manifest('yaml')], ['ConfigMap', 'Service'])

    def test_published_chart_rejects_unpublished_commit_and_dirty_chart(self):
        c = {'host': 'wsl'}
        with patch.object(f, 'source_state', return_value='main@sha1:old'), patch.object(f, 'run', return_value=subprocess.CompletedProcess([], 0, 'new', '')):
            with self.assertRaises(f.Pending): f.require_published_chart(c)
        results = [subprocess.CompletedProcess([], 0, 'same', ''), subprocess.CompletedProcess([], 0, ' M charts/lnd-ops/values.yaml', '')]
        with patch.object(f, 'source_state', return_value='main@sha1:same'), patch.object(f, 'run', side_effect=results):
            with self.assertRaises(f.Pending): f.require_published_chart(c)

    def test_adoption_does_not_enable_reconciliation_after_wallet_change(self):
        c = {'clusterUID': 'uid'}
        baseline = {'configDigest': f.digest(c), 'clusterUID': 'uid', 'lnd': {'pvcs': {'p': 'old'}, 'nodes': {}}}
        with patch.object(f, 'bound_config', return_value=c), patch.object(f, 'require_exercise'), \
                patch.object(f, 'require_backup'), patch.object(f, 'require_published_chart'), \
                patch.object(f, 'record', return_value=baseline), \
                patch.object(f, 'lnd_state', return_value=({'pvcs': {'p': 'new'}, 'nodes': {}}, {})), \
                patch.object(f, 'write') as write, patch.object(f, 'run') as run:
            with self.assertRaises(f.Pending): f.adopt('wsl')
        write.assert_not_called()
        run.assert_not_called()

    def test_acceptance_record_only_written_after_full_verification(self):
        with patch.object(f, 'verify', side_effect=f.Pending('channel mismatch')), patch.object(f, 'cm_record') as record:
            with self.assertRaises(f.Pending): f.accept('wsl')
        record.assert_not_called()

    def test_manifest_comparison_preserves_runtime_backup_data_only(self):
        old = [{'kind': 'ConfigMap', 'metadata': {'name': 'lnd-backup-status'}, 'data': {'lnd-0.status': 'old'}}]
        new = copy.deepcopy(old); new[0]['data']['lnd-0.status'] = 'current'
        current = {'data': {'lnd-0.status': 'current'}}
        with patch.object(f, 'get', return_value=current):
            f.compare_manifests(new, copy.deepcopy(old))
            with self.assertRaises(f.Pending): f.compare_manifests(old, copy.deepcopy(old))
            changed = copy.deepcopy(new); changed[0]['metadata']['labels'] = {'unexpected': 'change'}
            with self.assertRaises(f.Pending): f.compare_manifests(changed, copy.deepcopy(old))

    def test_refresh_export_refuses_any_started_handoff(self):
        c = {'host': 'wsl'}
        with tempfile.TemporaryDirectory() as tmp, patch.object(f, 'REPO', Path(tmp)), \
                patch.object(f, 'bound_config', return_value=c), patch.object(f, 'require_exercise'), \
                patch.object(f, 'require_backup'), patch.object(f, 'require_published_chart'), \
                patch.object(f, 'get', side_effect=[{'spec': {'suspend': True}, 'status': {}}, {'metadata': {'annotations': {f.OWNER: 'wsl'}}}]), \
                patch.object(f, 'lnd_state') as state:
            f.write(f.directory('wsl') / 'workloads/lnd.json', {'spec': {'suspend': True}})
            with self.assertRaises(f.Pending): f.export_lnd('wsl', refresh=True)
        state.assert_not_called()

    def test_lnd_state_reads_only_identity_channels_and_pvc(self):
        values = {'profile': 'testnet', 'lnd': {'nodes': 1}}
        info = {'identity_pubkey': '03' + 'a' * 64, 'synced_to_chain': True, 'synced_to_graph': True, 'num_peers': 1}
        responses = [{'info': {'status': 'deployed'}, 'version': 7}, values, info,
                     {'channels': [{'channel_point': 'tx:0', 'active': True}]}, {}]
        pvc = {'metadata': {'name': 'data-lnd-0-0', 'uid': 'pvc-uid'}, 'status': {'phase': 'Bound'}}
        with patch.object(f, 'read_json', side_effect=responses) as read, patch.object(f, 'get', return_value=pvc):
            state, actual_values = f.lnd_state()
        self.assertEqual(state['pvcs'], {'data-lnd-0-0': 'pvc-uid'})
        self.assertEqual(state['nodes']['lnd-0']['channels'], ['tx:0'])
        self.assertEqual(actual_values, values)
        self.assertEqual([c.args[-1] for c in read.call_args_list[2:]], ['getinfo', 'listchannels', 'pendingchannels'])

    def test_lnd_state_refuses_pending_channel_operations(self):
        values = {'profile': 'testnet', 'lnd': {'nodes': 1}}
        info = {'identity_pubkey': 'key', 'synced_to_chain': True, 'synced_to_graph': True, 'num_peers': 1}
        responses = [{'info': {'status': 'deployed'}, 'version': 1}, values, info, {'channels': []}, {'waiting_close_channels': [{'channel': {}}]}]
        pvc = {'metadata': {'name': 'data-lnd-0-0', 'uid': 'uid'}, 'status': {'phase': 'Bound'}}
        with patch.object(f, 'read_json', side_effect=responses), patch.object(f, 'get', return_value=pvc):
            with self.assertRaises(f.Pending): f.lnd_state()

    def test_no_config_returns_pending_without_cluster_commands(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(f, 'REPO', Path(tmp)), patch.object(f, 'run') as run, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(f.main(['verify-auto']), 10)
        run.assert_not_called()

    def test_verify_is_read_only_and_does_not_accept_missing_proof(self):
        with patch.object(f, 'bound_config', return_value={}), patch.object(f, 'controllers_ready'), \
                patch.object(f, 'require_exercise', side_effect=f.Pending('missing exercise')), patch.object(f, 'apply') as apply:
            with self.assertRaises(f.Pending): f.verify('wsl')
        apply.assert_not_called()


if __name__ == '__main__':
    unittest.main()
