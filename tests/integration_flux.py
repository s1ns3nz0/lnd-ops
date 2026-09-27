#!/usr/bin/env python3
"""Real Flux/Git/Helm reconciliation on a disposable Kind cluster, never a user cluster.
Requires Docker, kind, kubectl, helm and git. No external Git push or credentials.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ops'))
import flux_ops as f

NODE = 'kindest/node@sha256:4613778f3cfcd10e615029370f5786704559103cf27bef934597ba562b269661'
PYTHON = 'python@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26'


def cmd(*args, cwd=None):
    p = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if p.returncode:
        raise RuntimeError(p.stdout)
    return p.stdout.strip()


def wait(fn, label, timeout=240):
    until = time.monotonic() + timeout
    last = ''
    while time.monotonic() < until:
        try:
            result = fn()
            print('PASS ' + label, flush=True)
            return result
        except (f.Pending, KeyError) as error:
            detail = str(error)
            if detail != last:
                print('WAIT ' + label + ': ' + detail, flush=True)
            last = detail
            time.sleep(3)
    raise RuntimeError(label + ': ' + last)


def main():
    cache = ROOT / '.cache'
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='flux-integration-', dir=cache) as tmp:
        temp = Path(tmp)
        cluster = 'lnd-flux-' + str(os.getpid())
        server = cluster + '-git'
        os.environ['KUBECONFIG'] = str(temp / 'kubeconfig')
        work = temp / 'work'
        work.mkdir()
        f.REPO = work
        try:
            print('Creating disposable Linux Kind cluster ' + cluster, flush=True)
            cmd('kind', 'create', 'cluster', '--name', cluster, '--image', NODE, '--kubeconfig', os.environ['KUBECONFIG'], '--wait', '120s')
            for path in ('charts/flux', 'charts/gitops-probe'):
                shutil.copytree(ROOT / path, work / path)
            cmd('git', 'init', '-b', 'main', str(work))
            cmd('git', 'config', 'user.name', 'Flux integration fixture', cwd=work)
            cmd('git', 'config', 'user.email', 'fixture@localhost', cwd=work)
            served = temp / 'served'
            served.mkdir()
            bare = served / 'source.git'
            cmd('git', 'init', '--bare', '-b', 'main', str(bare))
            cmd('docker', 'build', '-t', 'localhost/lnd-ops-flux-git-test', str(ROOT / 'tests/flux'))
            cmd('docker', 'run', '-d', '--name', server, '--network', 'kind', '-v', f'{served}:/srv:ro', 'localhost/lnd-ops-flux-git-test')
            ip = cmd('docker', 'inspect', '--format', '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}', server)
            f.prepare('wsl', 'https://git.invalid/source.git', 'main')
            # Only this fixture uses a credential-free HTTP server on an isolated Docker network.
            c = f.config('wsl')
            c['url'] = f'http://{ip}:8000/source.git'
            f.write(f.directory('wsl') / 'config.json', c)
            bootstrap = json.loads((f.directory('wsl') / 'bootstrap.json').read_text())
            bootstrap['items'][0]['spec']['url'] = c['url']
            bootstrap['items'][0]['spec']['interval'] = '10s'
            bootstrap['items'][1]['spec']['interval'] = '10s'
            f.write(f.directory('wsl') / 'bootstrap.json', bootstrap)

            def publish(message):
                cmd('git', 'add', '.', cwd=work)
                cmd('git', 'commit', '-m', message, cwd=work)
                cmd('git', 'push', str(bare), 'main', cwd=work)
                cmd('git', '--git-dir', str(bare), 'update-server-info')
                return cmd('git', 'rev-parse', 'HEAD', cwd=work)

            publish('baseline')
            f.install('wsl')
            f.connect('wsl')
            wait(lambda: f.capture_probe('wsl', 'baseline'), 'Git baseline')
            f.stage_probe('wsl', 'failure')
            publish('intentional Helm rendering failure')
            wait(lambda: f.capture_probe('wsl', 'failure'), 'Git failure observed')
            f.stage_probe('wsl', 'recovery')
            publish('recover from rendering failure')
            wait(lambda: f.capture_probe('wsl', 'recovery'), 'Git recovery')
            f.require_exercise(c)
            # Adopt an existing Helm release, including a durable PVC and running Pod.
            chart = work / 'charts/adoption-fixture'
            (chart / 'templates').mkdir(parents=True)
            (chart / 'Chart.yaml').write_text('apiVersion: v2\nname: adoption-fixture\nversion: 0.1.0\n')
            (chart / 'templates/state.yaml').write_text('''apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: retained-data
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi
---
apiVersion: v1
kind: Pod
metadata:
  name: retained-node
spec:
  containers:
  - name: node
    image: ''' + PYTHON + '''
    command: [python, -c, "import pathlib,time; p=pathlib.Path('/data/identity'); p.write_text('same-wallet-fixture') if not p.exists() else None; time.sleep(3600)"]
    volumeMounts:
    - name: data
      mountPath: /data
  volumes:
  - name: data
    persistentVolumeClaim:
      claimName: retained-data
''')
            cmd('kubectl', 'create', 'namespace', 'adoption-fixture')
            cmd('helm', 'install', 'retained-release', str(chart), '-n', 'adoption-fixture', '--wait', '--timeout', '180s')
            pvc_before = f.get('pvc', 'retained-data', 'adoption-fixture')['metadata']['uid']
            pod_before = f.get('pod', 'retained-node', 'adoption-fixture')['metadata']['uid']
            hr = f.helmrelease('retained-release', './charts/adoption-fixture', 'adoption-fixture', {})
            f.write(f.directory('wsl') / 'workloads/adoption.json', hr)
            kpath = f.directory('wsl') / 'workloads/kustomization.yaml'
            k = json.loads(kpath.read_text()); k['resources'].append('adoption.json'); f.write(kpath, k)
            expected = publish('adopt existing Helm release')
            def adoption():
                rev = f.source_state(c)
                if not rev.endswith(expected):
                    raise f.Pending('new Git commit pending')
                f.release_state('retained-release', rev)
            wait(adoption, 'existing Helm adoption')
            assert f.get('pvc', 'retained-data', 'adoption-fixture')['metadata']['uid'] == pvc_before
            assert f.get('pod', 'retained-node', 'adoption-fixture')['metadata']['uid'] == pod_before
            assert cmd('kubectl', '-n', 'adoption-fixture', 'exec', 'retained-node', '--', 'cat', '/data/identity') == 'same-wallet-fixture'
            try:
                f.guard('adoption-fixture', 'retained-release')
            except f.Pending:
                print('PASS direct deployment guard', flush=True)
            else:
                raise AssertionError('guard allowed a Flux-managed release')
            print('PASS retained PVC, Pod UID and durable identity data; real Helm adoption', flush=True)
            # Exercise production export/adopt/verify against another real Helm release.
            # Only wallet RPC + backup evidence are fixtures; controllers/Git/Helm/storage are real.
            lndchart = work / 'charts/lnd-ops'
            shutil.copytree(chart, lndchart)
            (lndchart / 'values.yaml').write_text('profile: testnet\nlnd:\n  nodes: 1\nmonitoring:\n  enabled: true\n  paymentCollectorImage: fixture\n')
            shutil.copy(ROOT / 'charts/lnd-ops/templates/backup-status-configmap.yaml', lndchart / 'templates/backup-status.yaml')
            cmd('kubectl', 'create', 'namespace', 'lnd-testnet')
            cmd('helm', 'install', 'lnd-ops', str(lndchart), '-n', 'lnd-testnet', '--wait', '--timeout', '180s')
            cmd('kubectl', '-n', 'lnd-testnet', 'patch', 'configmap', 'lnd-backup-status', '--type=merge', '-p', json.dumps({'data': {'lnd-0.status': 'runtime-backup-proof'}}))
            expected = publish('prepare wallet-free handoff fixture')
            wait(lambda: f.require_published_chart(c), 'published chart before export')
            def fixture_wallet():
                status = f.read_json('helm', '-n', 'lnd-testnet', 'status', 'lnd-ops', '-o', 'json')
                values = f.read_json('helm', '-n', 'lnd-testnet', 'get', 'values', 'lnd-ops', '--all', '-o', 'json')
                uid = f.get('pvc', 'retained-data', 'lnd-testnet')['metadata']['uid']
                identity = cmd('kubectl', '-n', 'lnd-testnet', 'exec', 'retained-node', '--', 'cat', '/data/identity')
                return {'revision': status['version'], 'valuesDigest': f.digest(values), 'pvcs': {'retained-data': uid},
                        'nodes': {'fixture': {'pubkey': identity, 'channels': [], 'active': []}}}, values
            with patch.object(f, 'lnd_state', side_effect=fixture_wallet), patch.object(f, 'require_backup'):
                before, _ = fixture_wallet()
                f.export_lnd('wsl')
                publish('publish suspended handoff')
                def suspended():
                    f.require_published_chart(c)
                    hr = f.get('helmrelease', 'lnd-ops')
                    if not hr['spec'].get('suspend'):
                        raise f.Pending('suspended resource pending')
                wait(suspended, 'suspended release published')
                wait(lambda: f.export_lnd('wsl', refresh=True), 'refresh suspended baseline')
                f.adopt('wsl')
                publish('activate reviewed handoff')
                wait(lambda: f.accept('wsl'), 'production handoff acceptance')
                f.verify('wsl')
                assert f.get('configmap', 'lnd-backup-status', 'lnd-testnet')['data']['lnd-0.status'] == 'runtime-backup-proof'
                after, _ = fixture_wallet()
                assert before['pvcs'] == after['pvcs'] and before['nodes'] == after['nodes']
                try:
                    f.guard('lnd-testnet', 'lnd-ops')
                except f.Pending:
                    pass
                else:
                    raise AssertionError('persistent handoff guard missing')
            print('PASS export/adopt/verify commands with real Git/Helm and explicit wallet RPC fixture', flush=True)

        finally:
            cmd('docker', 'rm', '-f', server) if subprocess.run(['docker', 'inspect', server], capture_output=True).returncode == 0 else None
            cmd('kind', 'delete', 'cluster', '--name', cluster)
    print('PASS Flux integration (no live LND or funded wallet touched)', flush=True)


if __name__ == '__main__':
    main()
