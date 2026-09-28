"""Interactive manual and first-success automatic Loop exercise."""
import select
import sys

from loop_api import LoopError
from loop_ops import DEFAULT_PAYMENT_TIMEOUT, Operations, channel_id, cost, number, state_of


def read_number(prompt, default=None, minimum=1):
    raw = input(prompt + (f' [Enter={default}]' if default is not None else '') + ': ').strip()
    return number(default if not raw and default is not None else raw, minimum=minimum)


def pick_channel(ops):
    channels = ops.channels()
    if not channels:
        raise LoopError('활성 채널이 없습니다.')
    wallet = ops.api.lnd('walletbalance')
    print(f"  온체인 확정 {wallet['confirmed_balance']} sat / anchor 예약 {wallet.get('reserved_balance_anchor_chan', 0)} sat")
    for i, channel in enumerate(channels, 1):
        print(f"  [{i}] peer {channel['remote_pubkey']}\n      SCID {channel_id(channel)} / 내 잔액 {channel['local_balance']} / 상대 잔액 {channel['remote_balance']} sat")
    index = read_number('  대상 채널 번호') - 1
    if index >= len(channels):
        raise LoopError('목록의 채널 번호를 입력하세요.')
    return channels[index]


def fee_notice():
    print('  수수료 예산은 새 swap 시작 한도입니다. 진행 중 자금 회수 비용은 초과할 수 있습니다.')
    print('  실행 후 화면 종료는 swap 취소가 아닙니다. Loop와 LND를 유지하세요.')


def show_failed_out(ops, record):
    """Read-only diagnosis of the latest failed Out; never quote or retry."""
    print('  == 최근 Loop Out 실패 진단 ==')
    confirmed_failed = False
    try:
        payments = ops.api.lnd('listpayments', '--include_incomplete').get('payments', [])
        matches = [p for p in payments if p.get('payment_hash') == record.get('swap_id')]
        if len(matches) != 1:
            print('  LND 결제 기록 미확인: 실패 원인을 단정할 수 없습니다.')
        else:
            payment = matches[0]
            status = payment.get('status', 'UNKNOWN')
            reason = payment.get('failure_reason', 'UNKNOWN')
            confirmed_failed = status == 'FAILED'
            print(f'  본 결제: {status} / {reason}')
            if status != 'FAILED':
                print('  결제 종료 미확인: 새 요청 없이 현재 결제·HTLC를 확인하세요.')
            elif reason == 'FAILURE_REASON_NO_ROUTE':
                print('  요청 조건에서 결제 경로를 확보하지 못했습니다. 기다려도 이 요청은 재개되지 않습니다.')
                print('  이후 경로 상황은 바뀔 수 있지만, 새 요청에는 별도 승인이 필요합니다.')
                print('  외부 채널의 잔액은 알 수 없습니다. 금액·선택 채널·경로를 재검토하세요.')
            elif reason == 'FAILURE_REASON_TIMEOUT':
                print('  결제 시도 시간이 만료됐습니다. 기존 HTLC 종료를 확인한 뒤 경로와 제한 시간을 검토하세요.')
            else:
                print('  LND 결제 실패 사유를 확인하세요. 같은 조건으로 자동 재시도하지 않습니다.')
    except (LoopError, ValueError, KeyError, TypeError):
        print('  LND 실패 상세 조회 실패: swap의 최종 상태와 별도로 확인이 필요합니다.')
    try:
        terms = ops.api.loop('/v1/loop/out/terms')
        minimum = number(terms['min_swap_amount'], minimum=1)
        maximum = number(terms['max_swap_amount'], minimum=minimum)
        print(f'  현재 서버 허용 금액: {minimum:,}~{maximum:,} sat')
        if not confirmed_failed:
            print('  본 결제 종료가 확인되기 전에는 재시도를 검토하지 마세요.')
        elif minimum < record['amount']:
            print('  더 작은 금액을 검토할 수 있습니다. 새 견적·수수료 확인과 수동 승인이 필요하며 성공은 보장되지 않습니다.')
        else:
            print('  현재 서버 최소 금액 때문에 이전보다 작은 금액으로 재시도할 수 없습니다.')
    except (LoopError, ValueError, KeyError, TypeError):
        print('  서버 금액 범위 조회 실패: 더 작은 금액의 가능 여부는 미확인입니다.')


def show(ops):
    _, journal, swaps = ops.reconcile()
    print('\n  == Phase 4 · Loop ==')
    count = sum(state_of(s) == 'SUCCESS' and number(s.get('amt', 0)) > 0 and s.get('type', 'LOOP_OUT') in ('LOOP_IN', 'LOOP_OUT') for s in swaps)
    print(f'  실제 성공 {count}건 / Phase 4: ' + ('완료' if count else '미완료'))
    print('  자동 실행: ' + ('승인됨 (이 화면의 감시 실행 중에만 시작)' if journal['automatic'].get('enabled') else 'OFF'))
    for record in journal['records'][-5:]:
        print(f"  {record['direction'].upper()} {record['amount']:,} sat / {record['status']} / 비용 {record.get('actual_fee', 0):,} sat")
        print(f"    요청 {record['label']} / swap {record.get('swap_id', '응답 확인 대기')}")
        if record.get('failure_reason'):
            print(f"    결과 사유: {record['failure_reason']}")
        if record['status'] == 'FAILED':
            print('    예산: 실제 비용으로 정산 완료' if record.get('budget_settled') else '    예산: 비용 예약 유지 (종료·결제·HTLC 확인 필요)')
        if record['status'] in ('SUBMITTING', 'UNKNOWN'):
            print('    결과 미확인: 재전송 금지. 같은 요청 label로 daemon 기록을 확인하세요.')
        if record.get('actual_fee', 0) > record['reservation']:
            print('    수수료 한도 초과: 추가 자동 실행 중지. 실제 회수 비용을 확인하세요.')
    tracked = {r['label'] for r in journal['records']}
    for swap in swaps[-5:]:
        if swap.get('label') not in tracked:
            print(f"  기타 swap {swap.get('id', '')}: {swap.get('type', 'LOOP_OUT')} / {state_of(swap)} / 비용 {cost(swap)} sat")
    if journal['records']:
        latest = journal['records'][-1]
        if (latest['direction'] == 'out' and latest['status'] == 'FAILED'
                and all(state_of(s) in ('SUCCESS', 'FAILED') for s in swaps)):
            show_failed_out(ops, latest)
    return count


def manual(ops, direction):
    channel = pick_channel(ops)
    terms = ops.api.loop(f'/v1/loop/{direction}/terms')
    print(f"  서버 금액 범위: {terms['min_swap_amount']}~{terms['max_swap_amount']} sat")
    amount = read_number('  swap 금액 (sat)')
    limit = read_number('  이번 수수료 시작 한도 (sat)')
    routing = read_number('  결제별 라우팅 수수료 상한 (sat)', 10, 0) if direction == 'out' else 0
    timeout = read_number('  결제 시도 제한 시간 (초, 1~1800)', DEFAULT_PAYMENT_TIMEOUT) if direction == 'out' else DEFAULT_PAYMENT_TIMEOUT
    budget = read_number('  최근 24시간 수수료 예산 (sat)', limit)
    plan = ops.plan(direction, channel_id(channel), amount, limit, routing, timeout)
    print(f"  노드 {plan['binding']['identity']} / Loop {direction.upper()} / {amount:,} sat")
    print(f"  서버 수수료 {plan['payload']['max_swap_fee']} / 채굴 예상 {plan['miner_estimate']} / 채굴 시작 상한 {plan['payload']['max_miner_fee']} sat")
    if direction == 'out':
        print(f"  선결제 {plan['payload']['max_prepay_amt']} sat (서버 비용 일부), 라우팅 한도 각각 {routing} sat")
        print('  반환 주소: 같은 LND의 온체인 지갑')
        print(f'  결제 시도 제한 {timeout}초 / 기존 HTLC 해소까지 전체 대기는 더 길어질 수 있습니다.')
    else:
        print('  자금 출처: 같은 LND의 온체인 지갑 / 수신 경로: 선택한 peer')
    print(f"  이번 비용 예약 {plan['reservation']:,} / 최근 24시간 예산 {budget:,} sat")
    fee_notice()
    phrase = f"SWAP {amount}"
    if input(f'  실행하려면 {phrase} 입력: ').strip() != phrase:
        print('  실행하지 않았습니다.')
        return
    label = ops.submit(plan, budget)
    print(f'  요청 전송 완료: {label}')
    watch(ops)


def watch(ops, approval_id=None):
    print('  10초마다 상태 갱신. q + Enter: 새 자동 실행 중지·화면 복귀 / 진행 중 swap은 유지')
    try:
        while True:
            if approval_id:
                print('  ' + ops.auto_tick(approval_id))
            show(ops)
            # Balance changes are shown alongside the swap, not inferred from it.
            for channel in ops.channels():
                print(f"  {channel_id(channel)}: 내 {channel['local_balance']} / 상대 {channel['remote_balance']} sat")
            wallet = ops.api.lnd('walletbalance')
            print(f"  온체인 확정 {wallet['confirmed_balance']} / 미확정 {wallet.get('unconfirmed_balance', 0)} sat")
            ready, _, _ = select.select([sys.stdin], [], [], 10)
            if ready:
                line = sys.stdin.readline()
                if not line or line.strip().lower() == 'q':
                    return
    finally:
        if approval_id:
            ops.disarm(approval_id)


def automatic(ops):
    channel = pick_channel(ops)
    print('  local 잔액 비율이 상한 초과면 Out, 하한 미만이면 In. 목표는 범위 중간값입니다.')
    print('  이 화면을 열어 둔 동안 감시하며, 첫 요청 뒤 추가 실행은 OFF가 됩니다.')
    rule = {'scid': channel_id(channel),
            'low': read_number('  목표 local 비율 하한 (%)', 30),
            'high': read_number('  목표 local 비율 상한 (%)', 70),
            'max_amount': read_number('  1회 최대 swap 금액 (sat)'),
            'fee_limit': read_number('  1회 수수료 시작 한도 (sat)'),
            'routing_limit': read_number('  결제별 라우팅 수수료 상한 (sat)', 10, 0),
            'daily_budget': read_number('  최근 24시간 수수료 예산 (sat)')}
    print(f"  채널 {rule['scid']} / 목표 {rule['low']}~{rule['high']}% / 최대 {rule['max_amount']:,} sat")
    print(f"  1회 수수료 {rule['fee_limit']:,} / 최근 24시간 예산 {rule['daily_budget']:,} sat")
    print(f'  Loop Out 결제 시도 제한 {DEFAULT_PAYMENT_TIMEOUT}초 (기존 HTLC 해소 시간 별도)')
    fee_notice()
    if input('  자동 실행을 승인하려면 AUTO 1 입력: ').strip() != 'AUTO 1':
        print('  자동 실행을 켜지 않았습니다.')
        return
    approval_id = ops.arm(rule)
    watch(ops, approval_id)


def interactive(env=None):
    from loop_api import API
    ops = Operations(API(env))
    if not sys.stdin.isatty():
        print('Loop 실행은 대화형 터미널에서만 승인할 수 있습니다.')
        return 'partial'
    while True:
        try:
            complete = show(ops)
            print('  [1] 수동 Loop Out  [2] 수동 Loop In  [a] 자동 swap (첫 성공 후 정지)')
            print('  [v] 실시간 상태  [s] 새 자동 실행 중지  [c] 인증 파일 생성·교체  [q] 돌아가기')
            choice = input('  선택: ').strip().lower()
            if choice == 'q':
                return 'complete' if complete else 'partial'
            if choice in ('1', '2'):
                manual(ops, 'out' if choice == '1' else 'in')
            elif choice == 'a':
                automatic(ops)
            elif choice == 'v':
                watch(ops)
            elif choice == 's':
                ops.disarm()
                print('  새 자동 실행 OFF. 진행 중 swap은 취소되지 않습니다.')
            elif choice == 'c':
                return 'credentials'
        except LoopError as exc:
            print(f'  보류: {exc}')
            # Leave a visible recovery path even when the status API is down.
            try:
                recovery = input('  Enter=재조회 / q=돌아가기 / c=인증 교체: ').strip().lower()
            except (EOFError, KeyboardInterrupt):
                return 'partial'
            if recovery == 'c':
                return 'credentials'
            if recovery == 'q':
                return 'partial'
        except (EOFError, KeyboardInterrupt):
            return 'partial'
