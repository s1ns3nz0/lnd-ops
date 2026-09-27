"""Observe public/guest address recovery without changing host networking."""
import ipaddress
import time

from router_observation import current as current_external
from router_recovery import capture as host_capture, validate_observation
from router_rpc import call
from router_store import operation_lock, read, write


def capture(root):
    observation = host_capture()
    info = call('getinfo')
    receipt = read(root, 'p2p-observation.json')
    now = time.time()
    if info.get('identity_pubkey') != observation['wallet'] or not current_external(receipt, info, now=int(now)):
        raise ValueError('현재 지갑·공개 주소의 유효한 외부 접속 결과를 먼저 가져오세요')
    return observation | {'observed_at': now, 'external': receipt,
                          'endpoint': receipt['observation']['request']['endpoint']}


def validate(value):
    validate_observation(value)
    addresses = value.get('guest_addresses')
    if not isinstance(addresses, list) or not addresses or addresses != sorted(set(addresses)):
        raise ValueError('guest의 실제 IP 주소 관측이 필요합니다')
    for address in addresses:
        ipaddress.ip_address(address)
    info = {'testnet': True, 'synced_to_chain': True, 'identity_pubkey': value['wallet'],
            'uris': [value['wallet'] + '@' + value['endpoint']]}
    if not current_external(value['external'], info, now=int(value['observed_at'])):
        raise ValueError('관측 당시 유효한 외부 접속 결과가 없습니다')


def verify_pair(before, after):
    for value in (before, after):
        validate(value)
    if after['observed_at'] <= before['observed_at']:
        raise ValueError('변경 이후 관측 시각이 잘못되었습니다')
    for field in ('kind', 'identity_sha256'):
        if before['host'][field] != after['host'][field]:
            raise ValueError('같은 호스트에서 주소 변경을 검증해야 합니다')
    for field in ('cluster_uid', 'node_uid', 'wallet', 'pvc_uid', 'pv_uid', 'channels'):
        if before[field] != after[field]:
            raise ValueError('주소 변경 후 기존 구성 보존 실패: ' + field)
    changes = []
    if before['endpoint'] != after['endpoint']:
        changes.append('public_endpoint')
    if before['guest_addresses'] != after['guest_addresses']:
        changes.append('guest_address')
    if not changes:
        raise ValueError('공개 또는 guest IP 주소가 실제로 바뀌지 않았습니다')
    request = after['external']['observation']['request']
    if request['issued_at'] <= before['observed_at']:
        raise ValueError('변경 전 기준 저장 이후 발급한 새 외부 검사 요청이 필요합니다')
    if request['nonce'] == before['external']['observation']['request']['nonce']:
        raise ValueError('이전 외부 접속 결과를 재사용할 수 없습니다')
    return {'schema': 'lnd-ops/router-address-recovery/v1', 'result': 'pass',
            'kind': after['host']['kind'], 'changes': changes, 'before': before, 'after': after,
            'verified_at': after['observed_at'], 'elapsed_seconds': after['observed_at'] - before['observed_at'],
            'external_provenance': 'operator-controlled-unsigned'}


def prepare(root, observe=None):
    with operation_lock(root, 'recovery.lock'):
        if read(root, 'address-recovery-pending.json'):
            raise ValueError('주소 변경 기준이 이미 있습니다. 검증하거나 명시적으로 취소하세요')
        before = (observe or (lambda: capture(root)))()
        validate(before)
        write(root, 'address-recovery-pending.json', {'schema': 'lnd-ops/router-address-pending/v1', 'before': before})
        return before


def verify(root, observe=None):
    with operation_lock(root, 'recovery.lock'):
        pending = read(root, 'address-recovery-pending.json')
        if not isinstance(pending, dict) or pending.get('schema') != 'lnd-ops/router-address-pending/v1':
            raise ValueError('주소 변경 전 기준이 없습니다')
        after = (observe or (lambda: capture(root)))()
        result = verify_pair(pending['before'], after)
        write(root, 'address-recovery-' + result['kind'] + '.json', result)
        write(root, 'address-recovery-pending.json', None)
        return result


def cancel(root):
    with operation_lock(root, 'recovery.lock'):
        write(root, 'address-recovery-pending.json', None)


def historical(root, kind, current, now=None):
    now = time.time() if now is None else now
    try:
        record = read(root, 'address-recovery-' + kind + '.json')
        if record is None:
            return {'state': 'unverified'}
        if record.get('schema') != 'lnd-ops/router-address-recovery/v1' or record.get('result') != 'pass':
            raise ValueError('invalid address recovery record')
        result = verify_pair(record['before'], record['after'])
        if result['kind'] != kind or result['verified_at'] > now:
            raise ValueError('invalid host kind or time')
        channels = sorted(({'point': c['point'], 'id': c['id'], 'peer': c['peer']}
                           for c in current.get('channels', []) if c.get('active') and not c.get('private')),
                          key=lambda c: c['point'])
        comparable = bool(current.get('identity')) and current.get('code') != 'query_error'
        matches = current.get('identity') == record['after']['wallet'] and channels == record['after']['channels']
        return {'state': 'current_unavailable' if not comparable else 'verified_history' if matches else 'different_current_state',
                'history_valid': True, 'matches_current': matches if comparable else None,
                'verified_at': result['verified_at'], 'changes': result['changes'],
                'elapsed_seconds': result['elapsed_seconds'], 'external_provenance': result['external_provenance']}
    except (ValueError, KeyError, TypeError, AttributeError, OSError):
        return {'state': 'invalid_record'}
