"""Loop REST transport inside the existing Pod; credentials stay in the Pod."""
import json
import os
from pathlib import Path
import subprocess


class LoopError(RuntimeError):
    pass


POD_REQUEST = '''import json,ssl,sys
from urllib.request import Request,urlopen
from urllib.error import HTTPError
spec=json.loads(sys.argv[1])
try:
    context=ssl.create_default_context(cafile='/loop/testnet/tls.cert')
    with open('/loop/testnet/loop.macaroon','rb') as f: token=f.read().hex()
    body=spec.get('body')
    request=Request('https://127.0.0.1:8081'+spec['path'],
        data=None if body is None else json.dumps(body).encode(),
        headers={'Grpc-Metadata-macaroon':token,'Content-Type':'application/json'},
        method=spec['method'])
    with urlopen(request,context=context,timeout=40) as r: result=json.load(r)
    print(json.dumps(result))
except HTTPError as e:
    print(json.dumps({'transport_error':'Loop API HTTP '+str(e.code)}))
except FileNotFoundError:
    print(json.dumps({'transport_error':'Loop TLS 인증서 또는 인증 파일이 아직 생성되지 않았습니다.'}))
except PermissionError:
    print(json.dumps({'transport_error':'Loop 인증 파일 읽기 권한이 없습니다. Pod volume 권한을 확인하세요.'}))
except ssl.SSLError:
    print(json.dumps({'transport_error':'Loop TLS 인증서 검증에 실패했습니다.'}))
except Exception:
    print(json.dumps({'transport_error':'Loop API가 응답하지 않습니다. daemon 시작 상태를 확인하세요.'}))
'''


class API:
    def __init__(self, env=None):
        self.env = dict(os.environ if env is None else env)
        self.env.setdefault('KUBECONFIG', str(Path(self.env.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'lnd-ops/kubeconfig'))

    def command(self, args, data=None, optional=False):
        try:
            p = subprocess.run(args, input=None if data is None else json.dumps(data),
                               text=True, capture_output=True, env=self.env, timeout=55)
        except (OSError, subprocess.TimeoutExpired):
            raise LoopError('클러스터 응답을 확인하지 못했습니다. 실행 요청은 자동 재전송하지 않습니다.') from None
        if p.returncode:
            if optional and 'NotFound' in p.stderr:
                return None
            raise LoopError('클러스터 작업 실패: 연결·권한·Pod 상태를 확인하세요.')
        try:
            return json.loads(p.stdout)
        except ValueError:
            raise LoopError('클러스터 응답 형식이 올바르지 않습니다.') from None

    def lnd(self, *args):
        return self.command(['kubectl', '-n', 'lnd-testnet', 'exec', 'lnd-0-0', '-c', 'lnd', '--',
                             'lncli', '--lnddir=/data/.lnd', '--network=testnet', *args])

    def loop(self, path, body=None):
        spec = {'path': path, 'body': body, 'method': 'GET' if body is None else 'POST'}
        result = self.command(['kubectl', '-n', 'lnd-testnet', 'exec', 'deployment/loopd', '-c',
                               'loop-health', '--', 'python3', '-c', POD_REQUEST, json.dumps(spec)])
        if result.get('transport_error'):
            raise LoopError(self.startup_diagnostic() or result['transport_error'])
        return result

    def startup_diagnostic(self):
        """Surface known startup causes without exposing arbitrary daemon logs."""
        try:
            pods = self.command(['kubectl', '-n', 'lnd-testnet', 'get', 'pods',
                                 '-l', 'app.kubernetes.io/name=loopd', '-o', 'json'])
            notes = []
            for pod in pods.get('items', []):
                if pod['metadata'].get('deletionTimestamp'):
                    continue
                for container in pod.get('status', {}).get('containerStatuses', []):
                    if container['name'] != 'loopd' or container.get('ready'):
                        continue
                    current = container.get('state', {})
                    state = current.get('waiting') or current.get('terminated') or {}
                    reason = state.get('reason', 'API 시작 대기')
                    name = pod['metadata']['name']
                    for previous in (False, True):
                        args = ['kubectl', '-n', 'lnd-testnet', 'logs', name, '-c', 'loopd', '--tail=20']
                        if previous:
                            args.append('--previous')
                        logs = subprocess.run(args, env=self.env, capture_output=True, text=True, timeout=10)
                        if 'exec format error' in logs.stdout + logs.stderr:
                            return 'Loop 시작 실패: 실행 파일의 CPU 아키텍처가 노드와 다릅니다 (exec format error). ops/build-loop와 Loop 재배포가 필요합니다. 인증 파일 재생성으로 해결되지 않습니다.'
                    notes.append(f'loopd {reason} / 재시작 {container.get("restartCount", 0)}회')
            return 'Loop 아직 준비되지 않음: ' + ', '.join(notes) if notes else ''
        except (LoopError, OSError, subprocess.TimeoutExpired):
            return ''

    def binding(self):
        info = self.lnd('getinfo')
        if info.get('chains') != [{'chain': 'bitcoin', 'network': 'testnet'}]:
            raise LoopError('testnet 노드만 사용할 수 있습니다.')
        if not info.get('synced_to_chain') or not info.get('synced_to_graph'):
            raise LoopError('LND 지갑 unlock·체인·그래프 동기화가 필요합니다.')
        if self.loop('/v1/loop/info').get('network') != 'testnet':
            raise LoopError('Loop network가 testnet이 아닙니다.')
        deployment = self.command(['kubectl', '-n', 'lnd-testnet', 'get', 'deployment', 'loopd', '-o', 'json'])
        containers = deployment['spec']['template']['spec']['containers']
        args = next(c['args'] for c in containers if c['name'] == 'loopd')
        if '--lnd.host=lnd-0:10009' not in args or '--network=testnet' not in args:
            raise LoopError('Loop가 현재 testnet LND에 연결된 구성이 아닙니다.')
        ns = self.command(['kubectl', 'get', 'namespace', 'lnd-testnet', '-o', 'json'])
        return {'namespace_uid': ns['metadata']['uid'], 'identity': info['identity_pubkey']}

    def load(self):
        return self.command(['kubectl', '-n', 'lnd-testnet', 'get', 'configmap',
                             'lnd-ops-loop-operations', '-o', 'json'], optional=True)

    def save(self, document):
        verb = 'replace' if document.get('metadata', {}).get('resourceVersion') else 'create'
        return self.command(['kubectl', '-n', 'lnd-testnet', verb, '-f', '-', '-o', 'json'], document)
