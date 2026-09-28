"""Testnet Loop planning and durable, single-flight swap submission.

Journal updates use Kubernetes resourceVersion compare-and-swap. A submission
intent is persisted before calling Loop. Lost responses never trigger retries.
"""
import base64
import copy
import json
import hashlib
import time
import uuid
from urllib.parse import urlencode

from loop_api import API, LoopError

TERMINAL = {'SUCCESS', 'FAILED'}


def number(value, name='금액', minimum=0):
    if isinstance(value, bool):
        raise LoopError(f'{name}: 정수를 입력하세요.')
    try:
        result = int(str(value))
    except (TypeError, ValueError):
        raise LoopError(f'{name}: 정수를 입력하세요.') from None
    if result < minimum:
        raise LoopError(f'{name}: {minimum} 이상이어야 합니다.')
    return result


def state_of(swap):
    return swap.get('state', 'INITIATED')


def cost(swap):
    return sum(number(swap.get(k, 0)) for k in ('cost_server', 'cost_onchain', 'cost_offchain'))


def channel_id(channel):
    # Recent LND returns a hexadecimal channel ID plus numeric scid.
    value = str(channel.get('scid') or channel.get('chan_id', ''))
    if not value.isdecimal():
        raise LoopError('채널의 numeric SCID를 확인할 수 없습니다.')
    return value


class Operations:
    def __init__(self, api=None, clock=time.time):
        self.api = api or API()
        self.clock = clock

    def document(self):
        binding = self.api.binding()
        document = self.api.load()
        if document is None:
            return {'apiVersion': 'v1', 'kind': 'ConfigMap',
                    'metadata': {'name': 'lnd-ops-loop-operations', 'namespace': 'lnd-testnet'},
                    'data': {'state.json': json.dumps({'schema': 1, 'binding': binding,
                                                     'records': [], 'automatic': {'enabled': False}})}}
        try:
            state = json.loads(document['data']['state.json'])
            if state['binding'] != binding or state['schema'] != 1:
                raise LoopError('Loop 운영 기록의 클러스터·노드가 현재 대상과 다릅니다.')
        except (KeyError, ValueError, TypeError):
            raise LoopError('Loop 운영 기록을 읽을 수 없습니다. 새 실행을 중단합니다.') from None
        return document

    def write(self, document, state):
        updated = copy.deepcopy(document)
        updated['data']['state.json'] = json.dumps(state)
        return self.api.save(updated)

    def swaps(self):
        return self.api.loop('/v1/loop/swaps').get('swaps', [])

    def reconcile(self):
        document = self.document()
        state = json.loads(document['data']['state.json'])
        previous = copy.deepcopy(state)
        swaps = self.swaps()
        by_label = {}
        for swap in swaps:
            by_label.setdefault(swap.get('label', ''), []).append(swap)
        for record in state['records']:
            matches = by_label.get(record['label'], [])
            if len(matches) > 1:
                raise LoopError('동일 요청의 swap이 여러 건입니다. 추가 실행을 중단합니다.')
            if matches:
                swap = matches[0]
                if number(swap.get('amt')) != record['amount'] or swap.get('type', 'LOOP_OUT') != 'LOOP_' + record['direction'].upper():
                    raise LoopError('기록과 실제 swap이 일치하지 않습니다.')
                was_terminal = record['status'] in TERMINAL
                prior_fee = record.get('actual_fee', 0)
                record.update(status=state_of(swap), swap_id=swap.get('id', swap.get('id_bytes', '')),
                              actual_fee=cost(swap), failure_reason=swap.get('failure_reason', ''))
                if cost(swap) != prior_fee or (state_of(swap) in TERMINAL and not was_terminal):
                    record['cost_observed_at'] = self.clock()
                if state_of(swap) in TERMINAL and not was_terminal:
                    state['automatic']['enabled'] = False
            # An unobserved intent remains unresolved, even across restarts.
        if state != previous:
            document = self.write(document, state)
        return document, state, swaps

    def channels(self):
        return [c for c in self.api.lnd('listchannels').get('channels', []) if c.get('active')]

    def available(self, channel):
        local_reserve = number(channel.get('local_constraints', {}).get('chan_reserve_sat', channel.get('local_chan_reserve_sat', 0)))
        remote_reserve = number(channel.get('remote_constraints', {}).get('chan_reserve_sat', channel.get('remote_chan_reserve_sat', 0)))
        return (max(0, number(channel['local_balance']) - local_reserve - number(channel.get('commit_fee', 0))),
                max(0, number(channel['remote_balance']) - remote_reserve))

    def plan(self, direction, scid, amount, fee_limit, routing_limit=10):
        if direction not in ('out', 'in'):
            raise LoopError('Loop 방향은 out 또는 in이어야 합니다.')
        self.api.binding()
        amount = number(amount, minimum=1)
        fee_limit = number(fee_limit, '수수료 한도', 1)
        routing_limit = number(routing_limit, '라우팅 수수료 한도')
        channels = self.channels()
        selected = [c for c in channels if channel_id(c) == str(scid)]
        if len(selected) != 1 or selected[0].get('pending_htlcs'):
            raise LoopError('대상 채널이 비활성이거나 처리 중인 HTLC가 있습니다.')
        channel = selected[0]
        if direction == 'in' and sum(c['remote_pubkey'] == channel['remote_pubkey'] for c in channels) != 1:
            raise LoopError('Loop In은 마지막 peer만 지정합니다. 같은 peer의 활성 채널이 여러 개면 개별 채널을 보장할 수 없습니다.')
        terms = self.api.loop(f'/v1/loop/{direction}/terms')
        minimum = number(terms['min_swap_amount'])
        maximum = number(terms['max_swap_amount'])
        if not minimum <= amount <= maximum:
            raise LoopError(f'서버 허용 금액은 {minimum:,}~{maximum:,} sat입니다. 입력 금액은 자동으로 늘리지 않습니다.')
        deadline = int(self.clock()) + 1800
        query = {'conf_target': 6}
        if direction == 'out':
            query['swap_publication_deadline'] = deadline
        else:
            query['loop_in_last_hop'] = base64.b64encode(bytes.fromhex(channel['remote_pubkey'])).decode()
            query['private'] = str(bool(channel.get('private'))).lower()
        quote = self.api.loop(f'/v1/loop/{direction}/quote/{amount}?' + urlencode(query))
        server_fee = number(quote['swap_fee_sat'])
        miner_estimate = number(quote['htlc_sweep_fee_sat' if direction == 'out' else 'htlc_publish_fee_sat'], '채굴 수수료 견적')
        prepay = number(quote.get('prepay_amt_sat', 0)) if direction == 'out' else 0
        miner_limit = miner_estimate * 2
        reservation = max(server_fee, prepay) + miner_limit + (2 * routing_limit if direction == 'out' else 0)
        if reservation > fee_limit:
            raise LoopError(f'견적 기반 수수료 한도 {reservation:,} sat가 승인 한도 {fee_limit:,} sat보다 큽니다.')
        outbound, inbound = self.available(channel)
        wallet = self.api.lnd('walletbalance')
        onchain = max(0, number(wallet['confirmed_balance']) - number(wallet.get('locked_balance', 0)) - number(wallet.get('reserved_balance_anchor_chan', 0)))
        # The prepay is included in the total invoices (amount + server fee),
        # while sweep fees come from the on-chain payout. Cost-risk reservation
        # therefore differs from required Lightning sending balance.
        required_outbound = amount + server_fee + 2 * routing_limit
        if direction == 'out' and outbound < required_outbound:
            raise LoopError(f'송신 여력 부족: 약 {outbound:,} sat, 필요 {required_outbound:,} sat')
        if direction == 'in' and (inbound < amount or onchain < amount + reservation):
            raise LoopError(f'Loop In 잔액 부족: 수신 여력 {inbound:,}, 예약금 제외 온체인 {onchain:,} sat')
        payload = {'amt': str(amount), 'max_swap_fee': str(server_fee),
                   'max_miner_fee': str(miner_limit), 'initiator': 'lnd-ops-phase4'}
        if direction == 'out':
            payload.update(outgoing_chan_set=[str(scid)], max_swap_routing_fee=str(routing_limit),
                           max_prepay_routing_fee=str(routing_limit), max_prepay_amt=str(prepay),
                           sweep_conf_target=6, htlc_confirmations=3,
                           swap_publication_deadline=str(deadline), payment_timeout=60)
        else:
            payload.update(last_hop=base64.b64encode(bytes.fromhex(channel['remote_pubkey'])).decode(),
                           external_htlc=False, htlc_conf_target=6, private=bool(channel.get('private')))
        return {'label': 'lnd-ops-' + uuid.uuid4().hex,
                'payload_hash': hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
                'direction': direction, 'scid': str(scid), 'peer': channel['remote_pubkey'],
                'amount': amount, 'fee_limit': fee_limit, 'routing_limit': routing_limit,
                'reservation': reservation, 'miner_estimate': miner_estimate, 'created': self.clock(),
                'binding': self.api.binding(), 'payload': payload,
                'before': {'onchain': onchain, 'local': channel['local_balance'], 'remote': channel['remote_balance']}}

    def submit(self, plan, daily_budget, automatic=False, approval_id=None):
        if not 0 <= self.clock() - plan['created'] <= 60:
            raise LoopError('견적이 만료됐습니다. 다시 조회하고 승인하세요.')
        if hashlib.sha256(json.dumps(plan['payload'], sort_keys=True).encode()).hexdigest() != plan['payload_hash']:
            raise LoopError('승인할 견적의 요청 내용이 변경됐습니다.')
        if number(plan['payload']['amt']) != plan['amount']:
            raise LoopError('요청 금액과 견적이 다릅니다.')
        payload = plan['payload']
        if plan['direction'] == 'out':
            if payload.get('outgoing_chan_set') != [plan['scid']]:
                raise LoopError('요청 채널과 승인 채널이 다릅니다.')
            reserved = max(number(payload['max_swap_fee']), number(payload['max_prepay_amt'])) + number(payload['max_miner_fee']) + number(payload['max_swap_routing_fee']) + number(payload['max_prepay_routing_fee'])
        elif plan['direction'] == 'in':
            if payload.get('last_hop') != base64.b64encode(bytes.fromhex(plan['peer'])).decode():
                raise LoopError('요청 peer와 승인 peer가 다릅니다.')
            reserved = number(payload['max_swap_fee']) + number(payload['max_miner_fee'])
        else:
            raise LoopError('승인한 swap 방향이 올바르지 않습니다.')
        if reserved != plan['reservation'] or reserved > plan['fee_limit']:
            raise LoopError('요청 수수료와 승인 한도가 다릅니다.')
        document, state, swaps = self.reconcile()
        if any(r['label'] == plan['label'] for r in state['records']):
            raise LoopError('이미 제출한 견적입니다. 같은 요청을 재전송하지 않습니다.')
        if state['binding'] != plan['binding']:
            raise LoopError('승인한 노드와 현재 노드가 다릅니다.')
        if any(state_of(s) not in TERMINAL for s in swaps) or any(r['status'] not in TERMINAL for r in state['records']):
            raise LoopError('진행 중이거나 결과 미확인 요청이 있습니다. 중복 실행하지 않습니다.')
        channels = self.channels()
        selected = [c for c in channels if channel_id(c) == plan['scid'] and c['remote_pubkey'] == plan['peer']]
        if len(selected) != 1 or selected[0].get('pending_htlcs'):
            raise LoopError('승인 이후 채널 상태가 바뀌었습니다. 다시 견적을 확인하세요.')
        outbound, inbound = self.available(selected[0])
        required_outbound = plan['amount'] + number(plan['payload']['max_swap_fee']) + number(plan['payload'].get('max_swap_routing_fee', 0)) + number(plan['payload'].get('max_prepay_routing_fee', 0))
        if plan['direction'] == 'out' and outbound < required_outbound:
            raise LoopError('승인 이후 송신 잔액이 부족해졌습니다.')
        if plan['direction'] == 'in':
            wallet = self.api.lnd('walletbalance')
            available = number(wallet['confirmed_balance']) - number(wallet.get('locked_balance', 0)) - number(wallet.get('reserved_balance_anchor_chan', 0))
            if inbound < plan['amount'] or available < plan['amount'] + plan['reservation']:
                raise LoopError('승인 이후 Loop In 잔액이 부족해졌습니다.')
            if sum(c['remote_pubkey'] == plan['peer'] for c in channels) != 1:
                raise LoopError('같은 peer의 채널이 늘어났습니다. 다시 확인하세요.')
        params = self.api.loop('/v1/liquidity/params')
        if params.get('autoloop') or params.get('easy_autoloop'):
            raise LoopError('Loop 자체 Autoloop가 켜져 있습니다. 중복 자동 운영을 먼저 해제하세요.')
        if automatic:
            rule = state['automatic']
            if not rule.get('enabled') or rule.get('approval_id') != approval_id:
                raise LoopError('자동 실행 승인이 변경되거나 해제됐습니다.')
            if plan['scid'] != rule['scid'] or plan['amount'] > rule['max_amount'] or plan['reservation'] > rule['fee_limit'] or daily_budget != rule['daily_budget']:
                raise LoopError('자동 실행 승인 범위를 벗어났습니다.')
        budget = number(daily_budget, '하루 수수료 예산', 1)
        cutoff = self.clock() - 86400
        # Rolling 24 hours avoids midnight resets. Reserve at least the approved
        # cost, including ambiguous/failed requests. Untracked swaps count too.
        used = sum(max(r['reservation'], r.get('actual_fee', 0)) for r in state['records'] if max(r['created'], r.get('cost_observed_at', 0)) >= cutoff)
        labels = {r['label'] for r in state['records']}
        for swap in swaps:
            if swap.get('label') not in labels and number(swap.get('last_update_time', 0)) / 1e9 >= cutoff:
                used += cost(swap)
        if used + plan['reservation'] > budget:
            raise LoopError(f'최근 24시간 수수료 예산 부족: 예약·실제 비용 {used:,} + 이번 {plan["reservation"]:,} > {budget:,} sat')
        label = plan['label']
        record = {k: copy.deepcopy(v) for k, v in plan.items() if k != 'binding'}
        record.update(label=label, status='SUBMITTING', automatic=automatic)
        state['records'].append(record)
        state['automatic']['enabled'] = False  # one attempt; success/failure never rearms
        self.write(document, state)  # CAS claim before any money-moving request
        payload = dict(plan['payload'], label=label)
        try:
            self.api.loop('/v1/loop/' + plan['direction'], payload)
        except LoopError:
            raise LoopError(f'요청 결과 미확인 ({label}). 재전송하지 않습니다. 상태 조회로 확인하세요.') from None
        return label

    def arm(self, rule):
        document, state, swaps = self.reconcile()
        if any(state_of(s) not in TERMINAL for s in swaps) or any(r['status'] not in TERMINAL for r in state['records']):
            raise LoopError('진행 중·결과 미확인 swap을 먼저 확인하세요.')
        for name in ('max_amount', 'fee_limit', 'daily_budget'):
            rule[name] = number(rule[name], name, 1)
        rule['routing_limit'] = number(rule['routing_limit'])
        if not 0 < rule['low'] < rule['high'] < 100:
            raise LoopError('목표 잔액 범위는 0 < 하한 < 상한 < 100이어야 합니다.')
        if rule['fee_limit'] > rule['daily_budget']:
            raise LoopError('1회 수수료 한도가 하루 예산보다 큽니다.')
        channels = [c for c in self.channels() if channel_id(c) == rule['scid']]
        if len(channels) != 1:
            raise LoopError('승인할 활성 채널을 확인할 수 없습니다.')
        rule = dict(rule, peer=channels[0]['remote_pubkey'], channel_point=channels[0].get('channel_point', ''))
        state['automatic'] = dict(rule, enabled=True, approval_id=uuid.uuid4().hex)
        self.write(document, state)
        return state['automatic']['approval_id']

    def disarm(self, approval_id=None):
        document = self.document()
        state = json.loads(document['data']['state.json'])
        if state['automatic'].get('enabled') and (approval_id is None or state['automatic'].get('approval_id') == approval_id):
            state['automatic']['enabled'] = False
            self.write(document, state)

    def auto_tick(self, approval_id):
        _, state, _ = self.reconcile()
        rule = state['automatic']
        if not rule.get('enabled') or rule.get('approval_id') != approval_id:
            return '자동 실행 OFF / 진행 중 swap은 계속 처리됩니다.'
        channels = [c for c in self.channels() if channel_id(c) == rule['scid']]
        if not channels:
            return '대상 채널 연결 대기'
        channel = channels[0]
        if channel['remote_pubkey'] != rule['peer'] or channel.get('channel_point', '') != rule['channel_point']:
            self.disarm(approval_id)
            raise LoopError('승인한 채널의 identity가 바뀌었습니다.')
        local, remote = number(channel['local_balance']), number(channel['remote_balance'])
        total = local + remote
        if not total:
            return '채널 잔액 없음'
        ratio = local * 100 / total
        if rule['low'] <= ratio <= rule['high']:
            return f'조건 대기: local 비율 {ratio:.1f}% / 목표 {rule["low"]}~{rule["high"]}%'
        direction = 'out' if ratio > rule['high'] else 'in'
        target = total * (rule['low'] + rule['high']) // 200
        amount = min(rule['max_amount'], abs(local - target))
        try:
            plan = self.plan(direction, rule['scid'], amount, rule['fee_limit'], rule['routing_limit'])
            label = self.submit(plan, rule['daily_budget'], True, approval_id)
        except LoopError:
            self.disarm(approval_id)
            raise
        return f'자동 Loop {direction.upper()} 요청: {amount:,} sat / {label}'
