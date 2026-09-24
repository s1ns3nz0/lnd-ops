# 채널·유동성·결제

> capacity와 방향별 liquidity가 송수신 가능성에 미치는 영향

채널·유동성·결제


채널 capacity는 총량이고 liquidity는 방향이다. 로컬 잔액은 보내는 능력, 원격 잔액은 받는 능력의 한 입력이다. 활성 채널이 있어도 목표 금액 10,000 sats를 어느 방향으로도 처리하지 못할 수 있다.

관측은 active/inactive channel, peer, pending HTLC, inbound/outbound bandwidth, trailing-hour 결제 성공·실패·수수료·해결 시간을 함께 본다. 단일 실패는 라우팅의 정상 변동일 수 있으므로 이 프로젝트는 1시간 내 outgoing 실패 3회 이상을 경보 후보로 사용한다.

공식 근거: Lightning Terminal 채널 유동성

capacity가 충분한데 결제가 실패할 수 있는 이유는?필요한 방향의 local/remote balance, 전체 경로의 유동성, HTLC 한도, peer 연결 상태가 별도 조건이기 때문이다.
