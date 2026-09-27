"""Journaled, explicitly approved cooperative testnet channel closure."""
import re
import time

from router_rpc import call, require_testnet
from router_store import operation_lock, read, write

RECORD = 'close-requests.json'


def inventory(rpc=call):
    info = rpc('getinfo')
    require_testnet(info)
    return info['identity_pubkey'], rpc('listchannels').get('channels', [])


def status(root, rpc=call):
    """Caller holds the operation lock. Missing evidence never means closed."""
    identity, channels = inventory(rpc)
    records = read(root, RECORD) or []
    pending = rpc('pendingchannels')
    closed = rpc('closedchannels').get('channels', [])
    for record in records:
        if record['identity'] != identity:
            continue
        point = record['point']
        waiting = next((item for group in ('waiting_close_channels', 'pending_closing_channels',
                                           'pending_force_closing_channels')
                        for item in pending.get(group, [])
                        if item.get('channel', {}).get('channel_point') == point), None)
        done = next((c for c in closed if c.get('channel_point') == point), None)
        if waiting is not None:
            record['state'] = 'closing'
            if waiting.get('closing_txid'):
                record['closing_txid'] = waiting['closing_txid']
        elif done and done.get('closing_tx_hash') and int(done.get('close_height', 0)) > 0:
            record.update(state='closed', closing_txid=done['closing_tx_hash'])
    if records:
        write(root, RECORD, records)
    return identity, channels, [r for r in records if r['identity'] == identity]


def preview(point, rate, maximum, rpc=call):
    if not re.fullmatch(r'[0-9a-f]{64}:[0-9]+', point):
        raise ValueError('채널 식별자가 올바르지 않습니다')
    if type(rate) is not int or type(maximum) is not int or not 1 <= rate <= maximum <= 10000:
        raise ValueError('수수료율은 1~10,000 sat/vB이며 상한은 시작값 이상이어야 합니다')
    identity, channels = inventory(rpc)
    channel = next((c for c in channels if c.get('channel_point') == point), None)
    if not channel:
        raise ValueError('열린 채널 목록에 없습니다. 종료 상태를 조회하세요')
    if not channel.get('active'):
        raise ValueError('상대 연결이 비활성입니다. 다시 연결한 뒤 일반 종료하세요')
    if channel.get('pending_htlcs'):
        raise ValueError('처리 중인 결제가 있습니다. 결제 완료 뒤 다시 확인하세요')
    pending = rpc('pendingchannels')
    if any(item.get('channel', {}).get('channel_point') == point
           for group in ('waiting_close_channels', 'pending_closing_channels', 'pending_force_closing_channels')
           for item in pending.get(group, [])):
        raise ValueError('이미 종료 진행 중입니다. 중복 요청하지 않습니다')
    return dict(identity=identity, point=point, peer=channel['remote_pubkey'],
                local_sat=int(channel['local_balance']), capacity_sat=int(channel['capacity']),
                rate=rate, maximum=maximum)


def submit(root, plan, rpc=call):
    with operation_lock(root):
        _, _, records = status(root, rpc)
        if any(r['point'] == plan['point'] for r in records):
            raise ValueError('이 채널의 종료 요청 기록이 있습니다. 상태만 조회하세요')
        if preview(plan['point'], plan['rate'], plan['maximum'], rpc) != plan:
            raise ValueError('노드 또는 채널 잔액이 변경됐습니다. 다시 확인하고 승인하세요')
        records = read(root, RECORD) or []
        record = dict(plan, state='submitting', requested_at=int(time.time()))
        records.append(record)
        write(root, RECORD, records)
        try:
            result = rpc('closechannel', '--chan_point=' + plan['point'],
                         '--sat_per_vbyte=' + str(plan['rate']),
                         '--max_fee_rate=' + str(plan['maximum']), timeout=60)
            txid = result.get('closing_txid', '')
            if not re.fullmatch(r'[0-9a-f]{64}', txid):
                raise ValueError('종료 응답의 거래 ID를 확인할 수 없습니다')
            record.update(state='closing', closing_txid=txid)
        except BaseException:
            record['state'] = 'uncertain'
            write(root, RECORD, records)
            raise
        write(root, RECORD, records)
        return record
