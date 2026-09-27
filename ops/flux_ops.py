"""Flux transition operations. No implicit Git writes to a remote or wallet actions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parent.parent
NS = 'flux-system'
NAME = 'lnd-ops'
OWNER = 'lnd-ops.io/gitops-host'
INSTALL_OWNER = 'lnd-ops.io/flux-version'
CONTROLLERS = ('source-controller', 'kustomize-controller', 'helm-controller', 'notification-controller')


class Pending(RuntimeError):
    pass


def run(*args, data=None, check=True, timeout=120):
    p = subprocess.run([str(a) for a in args], input=data, text=True, capture_output=True, timeout=timeout)
    if check and p.returncode:
        # Do not echo input/values or credentials in command output.
        raise Pending(f'{args[0]} {args[1]} failed; inspect the target resource with kubectl (exit {p.returncode})')
    return p


def read_json(*args):
    return json.loads(run(*args).stdout)


def get(kind, name, namespace=NS, optional=False):
    args = ['kubectl', 'get', kind, name, '-o', 'json']
    if namespace:
        args += ['-n', namespace]
    if optional:
        args.append('--ignore-not-found')
    raw = run(*args).stdout
    return json.loads(raw) if raw.strip() else None


def apply(obj):
    run('kubectl', 'apply', '--server-side', '--field-manager=lnd-ops-flux', '-f', '-', data=json.dumps(obj))


def document(api, kind, name, spec=None, namespace=NS):
    obj = {'apiVersion': api, 'kind': kind, 'metadata': {'name': name}}
    if namespace:
        obj['metadata']['namespace'] = namespace
    if spec is not None:
        obj['spec'] = spec
    return obj


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n')


def directory(host):
    if host not in ('wsl', 'mac'):
        raise ValueError('host must be wsl or mac')
    return REPO / 'gitops' / 'clusters' / host


def config(host):
    path = directory(host) / 'config.json'
    if not path.exists():
        raise Pending(f'먼저 ops/flux-phase prepare --host {host} --url URL --branch BRANCH')
    return json.loads(path.read_text())


def context_uid():
    return get('namespace', 'kube-system', namespace=None)['metadata']['uid']


def bound_config(host):
    c = config(host)
    if c['clusterUID'] != context_uid():
        raise Pending('대상 클러스터 UID가 준비 기록과 다릅니다; kubeconfig를 확인하세요')
    return c


def cm_record(name, payload):
    obj = document('v1', 'ConfigMap', name)
    obj['data'] = {'record.json': json.dumps(payload, sort_keys=True)}
    apply(obj)


def record(name):
    cm = get('configmap', name, optional=True)
    if not cm:
        raise Pending(f'기록 없음: {name}')
    return json.loads(cm['data']['record.json'])


def ready(obj):
    if not obj or obj.get('spec', {}).get('suspend'):
        return False
    gen = obj['metadata'].get('generation')
    conditions = obj.get('status', {}).get('conditions', [])
    return any(c['type'] == 'Ready' and c['status'] == 'True' and c.get('observedGeneration') == gen for c in conditions) and not any(c['type'] in ('Stalled', 'Reconciling') and c['status'] == 'True' for c in conditions)


def require_ready(obj):
    if not ready(obj):
        name = obj['metadata']['name'] if obj else 'missing resource'
        reasons = ', '.join(c.get('reason', '') for c in (obj or {}).get('status', {}).get('conditions', []))
        raise Pending(f'{name}: Ready 대기 ({reasons}); kubectl -n flux-system get helmreleases,kustomizations,gitrepositories')


def source_state(c):
    src = get('gitrepository', NAME)
    if src['spec'].get('url') != c['url'] or src['spec'].get('ref') != {'branch': c['branch']}:
        raise Pending('Git source URL/ref가 준비 설정과 다릅니다')
    require_ready(src)
    ks = get('kustomization.kustomize.toolkit.fluxcd.io', NAME)
    require_ready(ks)
    if ks['spec'].get('sourceRef') != {'kind': 'GitRepository', 'name': NAME} or ks['spec'].get('path') != f"./gitops/clusters/{c['host']}/workloads" or ks['spec'].get('prune') is not False:
        raise Pending('Git 경로 또는 prune 설정이 다릅니다')
    revision = src['status']['artifact']['revision']
    if ks['status'].get('lastAppliedRevision') != revision:
        raise Pending('최신 Git revision 적용 대기')
    return revision


def release_state(name, revision, healthy=True):
    hr = get('helmrelease', name)
    if hr['spec'].get('chart', {}).get('spec', {}).get('sourceRef') != {'kind': 'GitRepository', 'name': NAME}:
        raise Pending('Helm chart의 Git source 참조가 다릅니다')
    if healthy:
        require_ready(hr)
    ref = hr.get('status', {}).get('helmChart', '')
    if '/' not in ref:
        raise Pending(f'{name}: HelmChart 생성 대기')
    namespace, chart = ref.split('/', 1)
    hc = get('helmchart', chart, namespace)
    require_ready(hc)
    if hc['status'].get('observedSourceArtifactRevision') != revision:
        raise Pending(f'{name}: 최신 chart revision 대기')
    if hr.get('status', {}).get('lastAttemptedRevision') != hc['status']['artifact']['revision']:
        raise Pending(f'{name}: 최신 chart 적용 시도 대기')
    return hr


def helmrelease(name, chart, target, values, suspended=False):
    return document('helm.toolkit.fluxcd.io/v2', 'HelmRelease', name, {
        'interval': '1m', 'timeout': '5m', 'releaseName': name,
        'targetNamespace': target, 'storageNamespace': target,
        'suspend': suspended,
        'chart': {'spec': {'chart': chart, 'version': '*', 'sourceRef': {'kind': 'GitRepository', 'name': NAME}, 'reconcileStrategy': 'Revision'}},
        'install': {'createNamespace': False, 'strategy': {'name': 'RetryOnFailure', 'retryInterval': '1m'}},
        'upgrade': {'strategy': {'name': 'RetryOnFailure', 'retryInterval': '1m'}, 'cleanupOnFail': False, 'force': False},
        'driftDetection': {'mode': 'disabled'},
        'values': values,
    })


def prepare(host, url, branch, secret=''):
    u = urlsplit(url)
    if u.scheme not in ('https', 'ssh') or not u.hostname or u.password or u.query or u.fragment or (u.scheme == 'https' and u.username):
        raise ValueError('Git URL은 자격증명 없는 https:// 또는 ssh:// 주소여야 합니다')
    if not branch or branch.startswith('-') or run('git', 'check-ref-format', '--branch', branch, check=False).returncode:
        raise ValueError('잘못된 Git branch')
    if secret and not re.fullmatch(r'[a-z0-9]([-a-z0-9.]*[a-z0-9])?', secret):
        raise ValueError('잘못된 Secret 이름')
    path = directory(host)
    if path.exists():
        raise ValueError(f'{path} 이미 존재합니다; 기존 설정을 덮어쓰지 않습니다')
    c = {'host': host, 'url': url, 'branch': branch, 'secretName': secret, 'clusterUID': context_uid()}
    write(path / 'config.json', c)
    source = document('source.toolkit.fluxcd.io/v1', 'GitRepository', NAME, {'interval': '1m', 'url': url, 'ref': {'branch': branch}})
    if secret:
        source['spec']['secretRef'] = {'name': secret}
    ks = document('kustomize.toolkit.fluxcd.io/v1', 'Kustomization', NAME, {
        'interval': '1m', 'retryInterval': '30s', 'timeout': '3m', 'path': f'./gitops/clusters/{host}/workloads',
        'prune': False, 'deletionPolicy': 'Orphan', 'sourceRef': {'kind': 'GitRepository', 'name': NAME},
    })
    write(path / 'bootstrap.json', {'apiVersion': 'v1', 'kind': 'List', 'items': [source, ks]})
    # A dedicated namespace has no wallet or workload Pods.
    write(path / 'workloads' / 'namespace.json', document('v1', 'Namespace', 'lnd-gitops-probe', namespace=None))
    write(path / 'workloads' / 'probe.json', helmrelease('lnd-ops-gitops-probe', './charts/gitops-probe', 'lnd-gitops-probe', {'marker': 'baseline', 'fail': False}))
    write(path / 'workloads' / 'kustomization.yaml', {'apiVersion': 'kustomize.config.k8s.io/v1beta1', 'kind': 'Kustomization', 'resources': ['namespace.json', 'probe.json']})
    print(f'생성: {path.relative_to(REPO)}. 검토 후 chart와 함께 Git commit/push하세요. 자동 push 없음.')


def install(host):
    bound_config(host)
    lock = json.loads((REPO / 'charts/flux/lock.json').read_text())
    manifest = REPO / 'charts/flux' / lock['file']
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != lock['sha256']:
        raise ValueError('Flux 설치 manifest checksum 불일치')
    # Do not downgrade or take over another installation.
    ns = get('namespace', NS, namespace=None, optional=True)
    if ns:
        existing = get('deployment', 'source-controller', optional=True)
        if existing and (existing['metadata'].get('labels', {}).get('app.kubernetes.io/version') != lock['version'] or ns['metadata'].get('annotations', {}).get(INSTALL_OWNER) != lock['version']):
            raise Pending('다른 Flux 설치가 있습니다; 별도 소유권/업그레이드 검토 필요')
    else:
        run('kubectl', 'create', 'namespace', NS)
    run('kubectl', 'annotate', 'namespace', NS, f"{INSTALL_OWNER}={lock['version']}", '--overwrite')
    run('kubectl', 'apply', '--server-side', '--field-manager=lnd-ops-flux', '-f', manifest)
    for controller in CONTROLLERS:
        print(f'Flux {controller} 준비 대기', flush=True)
        run('kubectl', '-n', NS, 'rollout', 'status', f'deployment/{controller}', '--timeout=180s', timeout=200)
    print(f"OK Flux {lock['version']} 설치; LND release는 아직 인계하지 않았습니다")


def connect(host):
    c = bound_config(host)
    if c['secretName']:
        # Existence only; never read or log credential contents.
        run('kubectl', '-n', NS, 'get', 'secret', c['secretName'], '-o', 'name')
    bootstrap = json.loads((directory(host) / 'bootstrap.json').read_text())
    old = get('gitrepository', NAME, optional=True)
    if old and old['spec'].get('url') != c['url']:
        raise Pending('다른 Git source가 있습니다; 자동 교체하지 않습니다')
    apply(bootstrap)
    print('Git source 연결 요청 완료. ops/flux-phase status로 동기화 상태를 확인하세요.')


def controllers_ready():
    lock = json.loads((REPO / 'charts/flux/lock.json').read_text())
    images = {tag.split(':')[0]: 'sha256:' + sha for tag, sha in lock['images'].items()}
    for name in CONTROLLERS:
        d = get('deployment', name)
        expected = 'ghcr.io/fluxcd/' + name
        actual = d['spec']['template']['spec']['containers'][0]['image']
        if actual != expected + '@' + images[expected]:
            raise Pending(f'{name}: 고정된 controller image와 다릅니다')
        s = d.get('status', {})
        if s.get('observedGeneration', 0) < d['metadata']['generation'] or s.get('availableReplicas', 0) < 1 or s.get('updatedReplicas', 0) < 1:
            raise Pending(f'{name} Deployment 준비 대기')


def stage_probe(host, stage):
    c = bound_config(host)
    if stage not in ('baseline', 'failure', 'recovery'):
        raise ValueError('unknown exercise stage')
    if stage != 'baseline':
        proof = record('lnd-ops-flux-exercise')
        validate_record(c, proof)
        prerequisite = 'baseline' if stage == 'failure' else 'failure'
        if prerequisite not in proof['stages']:
            raise Pending(f'{prerequisite} 증거를 먼저 record-probe로 확인하세요')
    path = directory(host) / 'workloads/probe.json'
    obj = json.loads(path.read_text())
    obj['spec']['values'] = {'marker': stage, 'fail': stage == 'failure'}
    write(path, obj)
    print(f'{path.relative_to(REPO)} 변경됨. Git commit/push 후 record-probe --stage {stage} 실행.')


def validate_record(c, proof):
    if proof.get('configDigest') != digest(c) or proof.get('clusterUID') != c['clusterUID']:
        raise Pending('기록이 현재 클러스터/Git 설정과 다릅니다')


def capture_probe(host, stage):
    c = bound_config(host)
    revision = source_state(c)
    hr = release_state('lnd-ops-gitops-probe', revision, healthy=stage != 'failure')
    expected = {'marker': stage, 'fail': stage == 'failure'}
    if hr['spec'].get('values') != expected:
        raise Pending('Git의 실습 설정이 아직 반영되지 않았습니다')
    if stage == 'failure':
        conds = hr.get('status', {}).get('conditions', [])
        if not any(x['type'] == 'Ready' and x['status'] == 'False' and x.get('observedGeneration') == hr['metadata']['generation'] and 'intentional GitOps probe failure' in x.get('message', '') for x in conds):
            raise Pending('의도한 Helm 렌더 실패가 아직 확인되지 않았습니다')
    else:
        cm = get('configmap', 'lnd-ops-gitops-probe', 'lnd-gitops-probe')
        if cm['data'].get('marker') != stage:
            raise Pending('실습 ConfigMap 적용 대기')
    old = get('configmap', 'lnd-ops-flux-exercise', optional=True)
    proof = json.loads(old['data']['record.json']) if old else {'configDigest': digest(c), 'clusterUID': c['clusterUID'], 'stages': {}}
    validate_record(c, proof)
    prerequisite = {'failure': 'baseline', 'recovery': 'failure'}.get(stage)
    if prerequisite and (prerequisite not in proof['stages'] or proof['stages'][prerequisite] == revision):
        raise Pending('이전 단계와 다른 Git revision 및 순차 검증이 필요합니다')
    if stage == 'baseline':
        proof['stages'] = {}
    elif stage == 'failure':
        proof['stages'].pop('recovery', None)
    proof['stages'][stage] = revision
    cm_record('lnd-ops-flux-exercise', proof)
    print(f'OK {stage}: {revision}')


def require_exercise(c):
    proof = record('lnd-ops-flux-exercise')
    validate_record(c, proof)
    if set(proof['stages']) != {'baseline', 'failure', 'recovery'} or len(set(proof['stages'].values())) != 3:
        raise Pending('테스트 release의 baseline → failure → recovery 검증이 필요합니다')
    rev = source_state(c)
    release_state('lnd-ops-gitops-probe', rev)
    if get('configmap', 'lnd-ops-gitops-probe', 'lnd-gitops-probe')['data'].get('marker') != 'recovery':
        raise Pending('테스트 release가 복구 상태가 아닙니다')


def lnd_state():
    status = read_json('helm', '-n', 'lnd-testnet', 'status', NAME, '-o', 'json')
    if status['info']['status'] != 'deployed':
        raise Pending('LND Helm release가 deployed 상태여야 합니다')
    values = read_json('helm', '-n', 'lnd-testnet', 'get', 'values', NAME, '--all', '-o', 'json')
    if values.get('profile') != 'testnet':
        raise Pending('testnet release만 인계할 수 있습니다')
    count = values.get('lnd', {}).get('nodes', 1)
    if not isinstance(count, int) or not 1 <= count <= 20:
        raise Pending('LND 노드 수 확인 필요')
    pvcs, nodes = {}, {}
    for i in range(count):
        name = f'lnd-{i}'
        pvc = get('pvc', f'data-{name}-0', 'lnd-testnet')
        if pvc.get('status', {}).get('phase') != 'Bound':
            raise Pending(f'{name} PVC not Bound')
        pvcs[pvc['metadata']['name']] = pvc['metadata']['uid']
        base = ('kubectl', '-n', 'lnd-testnet', 'exec', f'{name}-0', '-c', 'lnd', '--', 'lncli', '--lnddir=/data/.lnd', '--network=testnet')
        info = read_json(*base, 'getinfo')
        if not info.get('synced_to_chain') or not info.get('synced_to_graph') or not info.get('num_peers', 0):
            raise Pending(f'{name}: unlock·동기화·peer 연결 필요')
        channels = read_json(*base, 'listchannels').get('channels', [])
        pending = read_json(*base, 'pendingchannels')
        if any(pending.get(k) for k in ('pending_open_channels', 'pending_closing_channels', 'pending_force_closing_channels', 'waiting_close_channels')):
            raise Pending('대기 중인 채널 개설/종료가 끝난 뒤 인계하세요')
        nodes[name] = {'pubkey': info['identity_pubkey'], 'channels': sorted(c['channel_point'] for c in channels), 'active': sorted(c['channel_point'] for c in channels if c.get('active'))}
    return {'revision': status['version'], 'valuesDigest': digest(values), 'pvcs': pvcs, 'nodes': nodes}, values


def reject_secrets(values, path=''):
    if isinstance(values, dict):
        for key, value in values.items():
            at = f'{path}.{key}'.strip('.')
            if re.search(r'password|seed|mnemonic|private.?key|token|macaroon|api.?key', key, re.I) and value:
                if at != 'bitcoin.rpcPassword' or value != 'local-regtest-only':
                    raise ValueError(f'Git으로 내보낼 수 없는 credential 설정: {at}')
            reject_secrets(value, at)
    elif isinstance(values, list):
        for v in values:
            reject_secrets(v, path)


def normalized_manifest(raw):
    output = run('kubectl', 'create', '--dry-run=client', '--validate=false', '-f', '-', '-o', 'json', data=raw).stdout.strip()
    # kubectl emits adjacent JSON documents for a multi-document YAML input.
    items = []
    decoder = json.JSONDecoder()
    while output:
        data, end = decoder.raw_decode(output)
        items.extend(data.get('items', [data]))
        output = output[end:].lstrip()
    if not items:
        raise ValueError('빈 Helm manifest는 인계할 수 없습니다')
    return sorted(items, key=lambda x: (x['kind'], x['metadata']['name']))


def check_chart_unchanged(values):
    # Server dry-run is necessary for the backup-status Helm lookup.
    import tempfile
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / 'values.json'
        write(path, values)
        rendered = run('helm', 'template', NAME, REPO / 'charts/lnd-ops', '-n', 'lnd-testnet', '--is-upgrade', '--dry-run=server', '-f', path).stdout
    live = run('helm', '-n', 'lnd-testnet', 'get', 'manifest', NAME).stdout
    compare_manifests(normalized_manifest(rendered), normalized_manifest(live))


def compare_manifests(rendered, installed):
    # This ConfigMap is intentionally updated outside Helm by backup-status.
    # Permit its runtime data only if the server-side lookup preserves it exactly.
    for old in installed:
        if old['kind'] == 'ConfigMap' and old['metadata']['name'] == 'lnd-backup-status':
            current = get('configmap', 'lnd-backup-status', 'lnd-testnet')
            new = next((x for x in rendered if x['kind'] == 'ConfigMap' and x['metadata']['name'] == 'lnd-backup-status'), None)
            if not new or new.get('data') != current.get('data'):
                raise Pending('현재 backup-status 데이터가 Helm lookup에서 보존되지 않습니다')
            old['data'] = current['data']
    if rendered != installed:
        raise Pending('현재 chart 렌더 결과와 설치된 manifest가 다릅니다. 설정 변경을 인계와 분리하세요')


def require_backup():
    evidence = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'lnd-ops/evidence'
    paths = sorted(evidence.glob('phase5-acceptance-*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    if not paths:
        raise Pending('Phase 7 백업·복구 acceptance 기록이 필요합니다')
    path = paths[0]
    if path.is_symlink() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o777 != 0o600:
        raise Pending('백업·복구 증거 파일 권한을 확인하세요')
    proof = json.loads(path.read_text())
    if proof.get('schema') != 'lnd-ops/phase5-acceptance/v1' or proof.get('result') != 'pass' or proof.get('checks', {}).get('isolated_seed_and_scb_recovery') != 'pass':
        raise Pending('백업·복구 acceptance가 완료되지 않았습니다')
    run(REPO / 'ops/backup-status-encrypted', 'testnet', 'lnd-0', '--read-only')
    run(REPO / 'ops/router-backup-copy', '--status', '--json')


def require_published_chart(c):
    revision = source_state(c)
    head = run('git', '-C', REPO, 'rev-parse', 'HEAD').stdout.strip()
    if not revision.endswith(':' + head):
        raise Pending('로컬 HEAD와 Flux Git revision이 다릅니다; 검토한 commit을 먼저 반영하세요')
    changes = run('git', '-C', REPO, 'status', '--porcelain', '--', 'charts/lnd-ops', f"gitops/clusters/{c['host']}").stdout
    if changes.strip():
        raise Pending('chart/GitOps 파일에 미반영 변경이 있습니다; 검토·commit/push 후 다시 확인하세요')


def export_lnd(host, refresh=False):
    c = bound_config(host)
    require_exercise(c)
    require_backup()
    require_published_chart(c)
    path = directory(host) / 'workloads/lnd.json'
    if path.exists():
        if not refresh:
            raise Pending('LND 인계 파일이 이미 존재합니다; 인계 전 재준비는 export-lnd --refresh 사용')
        local = json.loads(path.read_text())
        hr = get('helmrelease', NAME)
        ns = get('namespace', 'lnd-testnet', namespace=None)
        if local['spec'].get('suspend') is not True or hr['spec'].get('suspend') is not True or hr.get('status', {}).get('history') or ns['metadata'].get('annotations', {}).get(OWNER):
            raise Pending('최초 인계가 시작되지 않은 suspended release만 baseline을 갱신할 수 있습니다')
    elif refresh:
        raise Pending('갱신할 suspended 인계 파일이 없습니다')
    state, values = lnd_state()
    reject_secrets(values)
    check_chart_unchanged(values)
    # Preserve all effective settings, including sidecars/NodePort/custom values.
    hr = helmrelease(NAME, './charts/lnd-ops', 'lnd-testnet', values, suspended=True)
    hr['metadata']['annotations'] = {'kustomize.toolkit.fluxcd.io/prune': 'disabled'}
    cm_record('lnd-ops-flux-baseline', {'configDigest': digest(c), 'clusterUID': c['clusterUID'], 'lnd': state})
    write(directory(host) / 'workloads/lnd.json', hr)
    path = directory(host) / 'workloads/kustomization.yaml'
    k = json.loads(path.read_text())
    if 'lnd.json' not in k['resources']:
        k['resources'].append('lnd.json')
    write(path, k)
    print('suspend=true LND HelmRelease 생성. Git commit/push 후 adopt를 실행하세요. 기존 release는 유지됩니다.')


def same_wallet(before, after):
    if before['pvcs'] != after['pvcs'] or before['nodes'] != after['nodes']:
        raise Pending('PVC UID·노드 identity·채널/활성 상태가 인계 전 기록과 다릅니다')


def adopt(host):
    c = bound_config(host)
    require_exercise(c)
    require_backup()
    require_published_chart(c)
    baseline = record('lnd-ops-flux-baseline')
    validate_record(c, baseline)
    before = baseline['lnd']
    after, values = lnd_state()
    same_wallet(before, after)
    if before['revision'] != after['revision'] or before['valuesDigest'] != after['valuesDigest']:
        raise Pending('인계 준비 후 Helm 설정이 변경됐습니다; 새 baseline 검토 필요')
    check_chart_unchanged(values)
    hr = get('helmrelease', NAME)
    if hr['spec'].get('suspend') is not True or hr['spec'].get('releaseName') != NAME or hr['spec'].get('targetNamespace') != 'lnd-testnet' or hr['spec'].get('storageNamespace') != 'lnd-testnet' or hr['spec'].get('values') != values:
        raise Pending('Git에 반영된 suspended HelmRelease와 기존 release 설정이 다릅니다')
    expected = helmrelease(NAME, './charts/lnd-ops', 'lnd-testnet', values, suspended=True)['spec']
    for key in ('install', 'upgrade', 'driftDetection', 'chart'):
        if hr['spec'].get(key) != expected[key]:
            raise Pending(f'인계 정책이 생성한 안전 설정과 다릅니다: {key}')
    path = directory(host) / 'workloads/lnd.json'
    local = json.loads(path.read_text())
    if local['spec'] != hr['spec']:
        raise Pending('로컬 파일과 클러스터의 suspended 설정이 다릅니다')
    # Mark ownership before enabling reconciliation; this persists through suspension.
    run('kubectl', 'annotate', 'namespace', 'lnd-testnet', f'{OWNER}={host}', '--overwrite')
    local['spec']['suspend'] = False
    write(path, local)
    print('직접 Helm 변경 차단됨. lnd.json의 suspend=false를 검토하고 Git commit/push하세요. 이후 accept로 인계 증거를 확인·저장하세요.')


def verify(host, initial=False):
    c = bound_config(host)
    controllers_ready()
    require_exercise(c)
    revision = source_state(c)
    hr = release_state(NAME, revision)
    if hr['spec'].get('targetNamespace') != 'lnd-testnet' or hr['spec'].get('storageNamespace') != 'lnd-testnet' or hr['spec'].get('releaseName') != NAME:
        raise Pending('LND Helm release 대상 불일치')
    baseline = record('lnd-ops-flux-baseline')
    validate_record(c, baseline)
    current, values = lnd_state()
    if initial:
        same_wallet(baseline['lnd'], current)
    else:
        accepted = record('lnd-ops-flux-acceptance')
        validate_record(c, accepted)
        if accepted.get('baselineDigest') != digest(baseline) or accepted.get('result') != 'pass':
            raise Pending('현재 baseline의 인계 완료 기록이 필요합니다; accept 실행')
        # Channel operations remain legitimate after the initial handoff proof.
        before = baseline['lnd']
        if before['pvcs'] != current['pvcs'] or {k: v['pubkey'] for k, v in before['nodes'].items()} != {k: v['pubkey'] for k, v in current['nodes'].items()}:
            raise Pending('인계 후 PVC 또는 LND identity가 변경됐습니다')
    if digest(hr['spec'].get('values')) != digest(values):
        raise Pending('Git HelmRelease values와 실제 Helm values 불일치')
    ns = get('namespace', 'lnd-testnet', namespace=None)
    if ns['metadata'].get('annotations', {}).get(OWNER) != host:
        raise Pending('직접 배포 차단 표식이 없습니다')
    print(f'OK Flux GitOps: {host}, {revision}; Git 실습·기존 release/PVC/identity와 인계 증거 검증')
    return {'configDigest': digest(c), 'clusterUID': c['clusterUID'], 'baselineDigest': digest(baseline),
            'revision': revision, 'result': 'pass'}


def accept(host):
    cm_record('lnd-ops-flux-acceptance', verify(host, initial=True))
    print('OK 최초 인계의 채널 보존 증거 저장. 이후 정상 채널 운영은 기존 완료 증거를 무효화하지 않습니다.')


def guard(namespace, release):
    ns = get('namespace', namespace, namespace=None, optional=True)
    if ns and ns['metadata'].get('annotations', {}).get(OWNER):
        host = ns['metadata']['annotations'][OWNER]
        raise Pending(f'Flux 관리 대상: 직접 Helm 변경/삭제 차단. ops/flux-phase edit-values --host {host} --patch FILE.json 후 Git 검토·commit/push하세요')
    crd = get('crd', 'helmreleases.helm.toolkit.fluxcd.io', namespace=None, optional=True)
    if not crd:
        return
    for hr in read_json('kubectl', 'get', 'helmreleases.helm.toolkit.fluxcd.io', '-A', '-o', 'json').get('items', []):
        spec = hr['spec']
        target = spec.get('targetNamespace', hr['metadata']['namespace'])
        storage = spec.get('storageNamespace', hr['metadata']['namespace'])
        default_name = f"{target}-{hr['metadata']['name']}" if spec.get('targetNamespace') else hr['metadata']['name']
        if namespace in (target, storage) and spec.get('releaseName', default_name) == release:
            raise Pending('Flux HelmRelease가 존재합니다 (suspend 포함). 직접 Helm 변경/삭제를 차단합니다. Git의 values를 수정하세요.')


def edit_values(host, patch):
    bound_config(host)
    changes = json.loads(Path(patch).read_text())
    if not isinstance(changes, dict) or not changes:
        raise ValueError('patch는 비어있지 않은 JSON object여야 합니다')
    reject_secrets(changes)
    def merge(a, b):
        for k, v in b.items():
            if isinstance(v, dict) and isinstance(a.get(k), dict):
                merge(a[k], v)
            else:
                a[k] = v
    path = directory(host) / 'workloads/lnd.json'
    obj = json.loads(path.read_text())
    old = obj['spec']['values']
    # Removing nodes or changing storage/identity is outside routine settings.
    if any(k in changes for k in ('profile', 'bitcoin')) or any(k in changes.get('lnd', {}) for k in ('nodes', 'storage')):
        raise ValueError('profile/bitcoin/노드 수/storage 변경은 별도 전환 검토가 필요합니다')
    merge(old, changes)
    write(path, obj)
    print(f'{path.relative_to(REPO)} 업데이트. git diff로 검토 후 commit/push하세요; 클러스터 직접 변경 없음.')


def status():
    for kind in ('deployments', 'gitrepositories', 'kustomizations.kustomize.toolkit.fluxcd.io', 'helmreleases'):
        p = run('kubectl', '-n', NS, 'get', kind, check=False)
        print(p.stdout.strip() or f'{kind}: 조회 불가 (Flux 미설치 또는 API 오류)')


def main(argv=None):
    os.environ.setdefault('KUBECONFIG', str(Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'lnd-ops/kubeconfig'))
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for name in ('prepare', 'install', 'connect', 'stage-probe', 'record-probe', 'export-lnd', 'adopt', 'verify', 'accept', 'edit-values'):
        p = sub.add_parser(name)
        p.add_argument('--host', choices=('wsl', 'mac'), required=True)
        if name in ('install', 'connect', 'export-lnd', 'adopt', 'record-probe', 'accept'):
            p.add_argument('--confirm', required=True, choices=[name.upper()])
        if name == 'prepare':
            p.add_argument('--url', required=True)
            p.add_argument('--branch', required=True)
            p.add_argument('--secret-name', default='')
        if name in ('stage-probe', 'record-probe'):
            p.add_argument('--stage', choices=('baseline', 'failure', 'recovery'), required=True)
        if name == 'export-lnd':
            p.add_argument('--refresh', action='store_true')
        if name == 'edit-values':
            p.add_argument('--patch', required=True)
    sub.add_parser('status')
    sub.add_parser('verify-auto')
    p = sub.add_parser('guard')
    p.add_argument('namespace')
    p.add_argument('release')
    args = parser.parse_args(argv)
    try:
        a = args.action
        if a == 'prepare': prepare(args.host, args.url, args.branch, args.secret_name)
        elif a == 'install': install(args.host)
        elif a == 'connect': connect(args.host)
        elif a == 'stage-probe': stage_probe(args.host, args.stage)
        elif a == 'record-probe': capture_probe(args.host, args.stage)
        elif a == 'export-lnd': export_lnd(args.host, args.refresh)
        elif a == 'adopt': adopt(args.host)
        elif a == 'verify': verify(args.host)
        elif a == 'accept': accept(args.host)
        elif a == 'edit-values': edit_values(args.host, args.patch)
        elif a == 'guard': guard(args.namespace, args.release)
        elif a == 'status': status()
        elif a == 'verify-auto':
            paths = [h for h in ('wsl', 'mac') if (directory(h) / 'config.json').exists()]
            if not paths:
                raise Pending('Phase 8 gitops 메뉴에서 대상 클러스터와 Git 설정을 준비하세요')
            uid = context_uid()
            matches = [h for h in paths if config(h)['clusterUID'] == uid]
            if len(matches) != 1:
                raise Pending('현재 클러스터와 일치하는 GitOps 설정이 정확히 하나여야 합니다')
            verify(matches[0])
    except (Pending, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f'PENDING: {exc}', file=sys.stderr)
        return 10
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f'CHECK: {exc}', file=sys.stderr)
        return 1
    return 0
