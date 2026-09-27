"""Host reboot observations; never initiate a restart or unlock a wallet."""
import hashlib
import ipaddress
import json
import math
import pathlib
import platform
import plistlib
import re
import runpy
import shutil
import subprocess
import time
from datetime import datetime
from urllib.parse import urlparse

from router_rpc import environment
from router_store import operation_lock, read, write


def output(command):
    return subprocess.check_output(command, env=environment(), text=True, timeout=30).strip()


def host_observation():
    if platform.system() == 'Darwin':
        boot = output(['sysctl', '-n', 'kern.bootsessionuuid'])
        boot_time = output(['sysctl', '-n', 'kern.boottime'])
        match = re.search(r'sec\s*=\s*(\d+)', boot_time)
        if not match or not re.fullmatch(r'[0-9A-Fa-f-]{36}', boot):
            raise ValueError('Mac 부팅 식별자를 확인할 수 없습니다')
        raw = subprocess.check_output(['ioreg', '-rd1', '-c', 'IOPlatformExpertDevice', '-a'], timeout=30)
        identity = plistlib.loads(raw)[0]['IOPlatformUUID']
        kind, started = 'mac', float(match[1])
    elif platform.system() == 'Linux' and 'microsoft' in platform.release().lower():
        powershell = shutil.which('powershell.exe') or '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
        script = ("$ErrorActionPreference='Stop'; $os=Get-CimInstance Win32_OperatingSystem; "
                  "$machine=Get-CimInstance Win32_ComputerSystemProduct; "
                  "@{identity=$machine.UUID; boot=$os.LastBootUpTime.ToUniversalTime().ToString('o')} | ConvertTo-Json -Compress")
        record = json.loads(output([powershell, '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', script]))
        identity, boot = record['identity'], record['boot']
        started = datetime.fromisoformat(boot.replace('Z', '+00:00')).timestamp()
        kind = 'windows'
    else:
        raise ValueError('호스트 재부팅 검증은 Mac 또는 Windows WSL에서 실행하세요')
    if not isinstance(identity, str) or not re.fullmatch(r'[0-9a-fA-F-]{36}', identity) or identity.lower().replace('-', '') in ('0' * 32, 'f' * 32):
        raise ValueError('호스트의 고유 식별자를 확인할 수 없습니다')
    return {'kind': kind, 'identity_sha256': hashlib.sha256(identity.lower().encode()).hexdigest(),
            'boot_id': boot, 'boot_started_at': started}


def capture():
    current = runpy.run_path(str(pathlib.Path(__file__).with_name('verify-router')))['snapshot']()
    if current.get('ready') is not True or not current.get('identity'):
        raise ValueError('Router 준비 필요: ' + str(current.get('message', '기존 지갑·채널 상태를 확인할 수 없습니다')))
    host = host_observation()
    server = output(['kubectl', 'config', 'view', '--minify', '-o', 'jsonpath={.clusters[0].cluster.server}'])
    hostname = urlparse(server).hostname
    if hostname != 'localhost' and not ipaddress.ip_address(hostname).is_loopback:
        raise ValueError('이 호스트의 로컬 Kubernetes API 연결에서만 재부팅 증거를 수집합니다')
    pod = json.loads(output(['kubectl', '-n', 'lnd-testnet', 'get', 'pod', 'lnd-0-0', '-o', 'json']))
    if not any(v.get('name') == 'data' and v.get('persistentVolumeClaim', {}).get('claimName') == 'data-lnd-0-0'
               for v in pod['spec']['volumes']):
        raise ValueError('LND Pod가 예상한 기존 지갑 PVC를 사용하지 않습니다')
    node = json.loads(output(['kubectl', 'get', 'node', pod['spec']['nodeName'], '-o', 'json']))
    namespace = json.loads(output(['kubectl', 'get', 'namespace', 'kube-system', '-o', 'json']))
    pvc = json.loads(output(['kubectl', '-n', 'lnd-testnet', 'get', 'pvc', 'data-lnd-0-0', '-o', 'json']))
    if pvc['status']['phase'] != 'Bound':
        raise ValueError('기존 지갑 PVC가 Bound 상태가 아닙니다')
    volume = pvc['spec']['volumeName']
    pv = json.loads(output(['kubectl', 'get', 'pv', volume, '-o', 'json']))
    if pv['spec']['claimRef']['uid'] != pvc['metadata']['uid']:
        raise ValueError('지갑 PVC와 PV 연결이 일치하지 않습니다')
    channels = sorted(({'point': c['point'], 'id': c['id'], 'peer': c['peer']}
                       for c in current['channels'] if c['active'] and not c['private']), key=lambda c: c['point'])
    return {'host': host, 'cluster_uid': namespace['metadata']['uid'],
            'node_uid': node['metadata']['uid'], 'guest_boot_id': node['status']['nodeInfo']['bootID'],
            'guest_addresses': sorted(a['address'] for a in node['status'].get('addresses', []) if a.get('type') == 'InternalIP'),
            'wallet': current['identity'], 'pvc_uid': pvc['metadata']['uid'], 'pv_uid': pv['metadata']['uid'],
            'channels': channels, 'ready': True, 'observed_at': time.time()}


def validate_observation(value):
    if not isinstance(value, dict) or value.get('ready') is not True:
        raise ValueError('준비 상태 관측이 없습니다')
    for field in ('cluster_uid', 'node_uid', 'guest_boot_id', 'wallet', 'pvc_uid', 'pv_uid'):
        if not isinstance(value.get(field), str) or not value[field]:
            raise ValueError('복구 관측의 identity 또는 storage 식별자가 없습니다')
    host = value['host']
    if host['kind'] not in ('mac', 'windows') or not re.fullmatch(r'[0-9a-f]{64}', host['identity_sha256']):
        raise ValueError('호스트 관측 식별자가 잘못되었습니다')
    if not isinstance(host['boot_id'], str) or not host['boot_id']:
        raise ValueError('호스트 부팅 식별자가 없습니다')
    for stamp in (host['boot_started_at'], value['observed_at']):
        if type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp <= 0:
            raise ValueError('관측 시각이 잘못되었습니다')
    if host['boot_started_at'] > value['observed_at']:
        raise ValueError('부팅 시각이 관측 시각보다 미래입니다')
    channels = value['channels']
    if not isinstance(channels, list) or len(channels) < 2:
        raise ValueError('공개 채널 두 개의 관측이 필요합니다')
    for channel in channels:
        for field in ('point', 'id', 'peer'):
            if not isinstance(channel.get(field), str) or not channel[field]:
                raise ValueError('채널 관측 식별자가 없습니다')
    if len({c['peer'] for c in channels}) < 2 or len({c['point'] for c in channels}) != len(channels):
        raise ValueError('서로 다른 공개 peer와 중복 없는 채널이 필요합니다')


def verify_pair(before, after):
    for observation in (before, after):
        validate_observation(observation)
    if after['observed_at'] <= before['observed_at']:
        raise ValueError('재부팅 이후 관측 시각이 잘못되었습니다')
    for field in ('kind', 'identity_sha256'):
        if before['host'][field] != after['host'][field]:
            raise ValueError('다른 호스트의 결과는 이 재부팅 증거에 사용할 수 없습니다')
    if before['host']['boot_id'] == after['host']['boot_id'] or after['host']['boot_started_at'] <= before['observed_at']:
        raise ValueError('기준 관측 이후 실제 호스트 재부팅을 확인하지 못했습니다. Pod·VM·WSL 재시작은 대체 증거가 아닙니다')
    if before['guest_boot_id'] == after['guest_boot_id']:
        raise ValueError('Kubernetes guest의 재부팅을 확인하지 못했습니다')
    for field in ('cluster_uid', 'node_uid', 'wallet', 'pvc_uid', 'pv_uid', 'channels'):
        if before[field] != after[field]:
            raise ValueError(f'재부팅 후 기존 구성 보존을 확인하지 못했습니다: {field}')
    return {'schema': 'lnd-ops/router-host-recovery/v1', 'result': 'pass',
            'kind': after['host']['kind'], 'before': before, 'after': after,
            'verified_at': after['observed_at'], 'elapsed_seconds': after['observed_at'] - before['observed_at'],
            'unlock_mode': 'manual', 'scope': 'host_reboot', 'external_p2p_verified': False}


def prepare(root, observe=capture):
    with operation_lock(root, 'recovery.lock'):
        pending = read(root, 'host-recovery-pending.json')
        if pending:
            raise ValueError('기존 재부팅 기준 기록이 있습니다. 검증하거나 cancel로 명시적으로 취소하세요')
        before = observe()
        validate_observation(before)
        write(root, 'host-recovery-pending.json', {'schema': 'lnd-ops/router-host-recovery-pending/v1', 'before': before})
        return before


def verify(root, observe=capture):
    with operation_lock(root, 'recovery.lock'):
        pending = read(root, 'host-recovery-pending.json')
        if not isinstance(pending, dict) or pending.get('schema') != 'lnd-ops/router-host-recovery-pending/v1':
            raise ValueError('재부팅 전 기준 기록이 없습니다')
        after = observe()
        result = verify_pair(pending['before'], after)
        write(root, 'host-recovery-' + result['kind'] + '.json', result)
        write(root, 'host-recovery-pending.json', None)
        return result


def cancel(root):
    with operation_lock(root, 'recovery.lock'):
        write(root, 'host-recovery-pending.json', None)


def historical(root, kind, current, now=None):
    now = time.time() if now is None else now
    try:
        record = read(root, 'host-recovery-' + kind + '.json')
        if record is None:
            return {'state': 'unverified'}
        if record.get('schema') != 'lnd-ops/router-host-recovery/v1' or record.get('result') != 'pass' or record.get('kind') != kind:
            raise ValueError('invalid recovery record')
        validated = verify_pair(record['before'], record['after'])
        if validated['kind'] != kind or validated['verified_at'] > now:
            raise ValueError('invalid recovery host or time')
        channels = sorted(({'point': c['point'], 'id': c['id'], 'peer': c['peer']} for c in current.get('channels', [])
                           if c.get('active') and not c.get('private')), key=lambda c: c['point'])
        comparable = bool(current.get('identity')) and current.get('code') != 'query_error'
        matches = current.get('identity') == record['after']['wallet'] and channels == record['after']['channels']
        return {'state': 'current_unavailable' if not comparable else 'verified_history' if matches else 'different_current_state',
                'history_valid': True, 'matches_current': matches if comparable else None,
                'verified_at': validated['verified_at'], 'elapsed_seconds': validated['elapsed_seconds'],
                'scope': 'host_reboot', 'unlock_mode': 'manual', 'external_p2p_verified': False}
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        return {'state': 'invalid_record'}
