---
title: 채널·유동성·결제
description: capacity와 방향별 liquidity가 송수신 가능성에 미치는 영향
versions: LND · lndmon 0.2.15
platforms: macOS arm64 · Windows WSL2 amd64
verified: 2026-09-24
commit: 841692b
status: 실제 환경 검증됨
scope: regtest · testnet
---
# 채널·유동성·결제
<MetadataCard versions="LND · lndmon 0.2.15" platforms="macOS arm64 · Windows WSL2 amd64" verified="2026-09-24" commit="841692b" status="실제 환경 검증됨" scope="regtest · testnet" />

지갑에 잔액이 있고 peer에 연결돼 있는데 결제가 실패할 수 있다. 그 이유를 이해하려면 온체인 지갑 잔액, 채널의 총 capacity, 방향별 liquidity를 따로 생각해야 한다. 이 장에서는 단순한 두 노드 예시로 시작해 실제 대시보드가 왜 여러 신호를 함께 보여주는지 설명한다.

## 한쪽에서 자금을 넣은 채널의 첫 상태

A가 B와 1,000,000 sat 채널을 열고 자금을 전부 부담했다고 하자. 수수료·reserve 등 제약을 생략한 학습용 계산에서는 A 쪽에 1,000,000 sat, B 쪽에 0 sat가 있다. 총 capacity는 충분해 보이지만 B는 이 채널로 A에게 즉시 큰 결제를 보낼 수 없다. B 쪽에 보낼 잔액이 없기 때문이다.

A가 B에게 100,000 sat를 지불하면 단순 모델에서 잔액은 A 900,000, B 100,000으로 바뀐다. 이제 A는 보낼 능력을 일부 소비한 대신 B로부터 받을 여유를 얻었다. 실제 사용 가능한 금액은 channel reserve, commitment fee, 진행 중인 HTLC 등으로 더 작을 수 있다. 따라서 local/remote balance를 결제 성공의 보장으로 읽지 않는다. 방향의 개념은 [Lightning Labs 유동성 설명](https://docs.lightning.engineering/lightning-network-tools/lightning-terminal/channel-liquidity)을 참고한다.

## 연결, 채널, 결제 경로는 서로 다른 상태다

peer 연결은 두 LND가 통신한다는 뜻이다. 채널은 자금 조달과 필요한 확인을 거쳐 결제에 사용할 수 있어야 한다. 그 채널이 active여도 목적지까지 이어지는 다른 채널에 유동성이 부족하면 다중 홉 결제는 실패한다.

HTLC(hash time-locked contract)는 조건을 만족하면 지급되고, 정해진 시간 조건에 따라 해소되는 결제 계약이다. 진행 중인 HTLC가 있으면 금액이나 슬롯이 일시적으로 묶일 수 있다. 운영자는 pending HTLC의 존재 자체보다 오래 유지되는지, 실패 증가나 peer 단절과 함께 나타나는지를 본다. 단순히 capacity를 더하는 것으로 이 상태를 설명할 수 없다.

## regtest에서 양방향 결제를 시험하는 이유

[`ops/exercise-regtest`](https://github.com/s1ns3nz0/lnd-ops/blob/master/ops/exercise-regtest)는 필요한 경우 첫 방향 결제로 상대에게 보낼 잔액을 만든 뒤, 10,000 sat 결제를 양방향으로 수행한다. 한쪽의 성공만 확인하면 반대 방향의 liquidity와 수신 지표는 검증되지 않는다.

또한 송신자의 성공 기록과 수신자의 settled invoice를 연결해 확인한다. “payment 명령이 반환됨”보다 강한 증거이며, collector가 실제 송수신 데이터를 읽는지 확인하는 데도 사용한다. 이 실습의 성공은 두 로컬 노드 경로의 검증이다. 공개 Lightning 네트워크의 다양한 경로에서 같은 성공률이 나온다는 뜻은 아니다.

## 대시보드에서 읽는 순서

먼저 active channel과 peer 상태로 연결성을 확인한다. 그다음 inbound와 outbound bandwidth로 어느 방향이 부족한지 본다. 마지막으로 결제 결과, 수수료, 관측된 HTLC 해소 시간을 함께 읽는다. Outbound가 충분한데 실패가 늘었다면 원격 경로나 수수료·시간 제약 등의 가능성이 남아 있다.

현재 10,000 sat 경보는 데모 목표에 대한 경고다. 여러 채널의 합이 그보다 커도 원하는 단일 경로로 보낼 수 있다는 보장은 없다. 또한 1시간 내 실패 3회 기준은 **연속 세 번 실패**나 실패율 3%를 뜻하지 않는다. 트래픽이 커지면 성공·실패의 분모와 사용자 영향을 반영한 기준으로 다시 설계해야 한다.

## 읽기 전용 연습

```sh
kubectl -n lnd-regtest exec lnd-0-0 -c lnd -- \
  lncli --lnddir=/data/.lnd --network=regtest listchannels
```

지갑이 열린 환경에서 각 채널의 `active`, `capacity`, `local_balance`, `remote_balance`를 읽는다. 여기서 볼 수 있는 정보로 설명 가능한 것은 이 노드의 채널 상태와 잔액이다. 원격 경로 전체의 유동성이나 다음 결제 성공을 확정할 수는 없다. 실제 출력에는 식별자가 있으므로 공개 학습 기록에는 필요한 수치만 정제한다.

<details class="quiz"><summary>1,000,000 sat capacity의 채널인데 10,000 sat를 받지 못한다면 무엇부터 볼까?</summary>채널이 active인지, 상대 방향의 가용 잔액이 있는지, 경로와 HTLC 제약은 무엇인지 확인한다. 총 capacity 하나로 수신 능력을 판단하지 않는다.</details>

다음 [관측과 경보](/07-observability/signals-to-decisions)는 이 판단 순서를 metric과 alert로 옮긴다.
