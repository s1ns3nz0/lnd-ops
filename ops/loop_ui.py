"""Interactive manual and first-success automatic Loop exercise."""
import select
import sys

from loop_api import LoopError
from loop_ops import Operations, channel_id, cost, number, state_of


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
        if record['status'] in ('SUBMITTING', 'UNKNOWN'):
            print('    결과 미확인: 재전송 금지. 같은 요청 label로 daemon 기록을 확인하세요.')
        if record.get('actual_fee', 0) > record['reservation']:
            print('    수수료 한도 초과: 추가 자동 실행 중지. 실제 회수 비용을 확인하세요.')
    tracked = {r['label'] for r in journal['records']}
    for swap in swaps[-5:]:
        if swap.get('label') not in tracked:
            print(f"  기타 swap {swap.get('id', '')}: {swap.get('type', 'LOOP_OUT')} / {state_of(swap)} / 비용 {cost(swap)} sat")
    return count


def manual(ops, direction):
    channel = pick_channel(ops)
    terms = ops.api.loop(f'/v1/loop/{direction}/terms')
    print(f"  서버 금액 범위: {terms['min_swap_amount']}~{terms['max_swap_amount']} sat")
    amount = read_number('  swap 금액 (sat)')
    limit = read_number('  이번 수수료 시작 한도 (sat)')
    routing = read_number('  결제별 라우팅 수수료 상한 (sat)', 10, 0) if direction == 'out' else 0
    budget = read_number('  최근 24시간 수수료 예산 (sat)', limit)
    plan = ops.plan(direction, channel_id(channel), amount, limit, routing)
    print(f"  노드 {plan['binding']['identity']} / Loop {direction.upper()} / {amount:,} sat")
    print(f"  서버 수수료 {plan['payload']['max_swap_fee']} / 채굴 예상 {plan['miner_estimate']} / 채굴 시작 상한 {plan['payload']['max_miner_fee']} sat")
    if direction == 'out':
        print(f"  선결제 {plan['payload']['max_prepay_amt']} sat (서버 비용 일부), 라우팅 한도 각각 {routing} sat")
        print('  반환 주소: 같은 LND의 온체인 지갑')
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
