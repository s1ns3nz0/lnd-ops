# 송금 성공과 중계 성공을 따로 확인한 이유

> Lightning 노드 운영 회고 5편 · Phase 3 후반 · 2026-09-27~28 실습 출력 기준

내가 보내는 결제와 남의 결제를 전달하는 일은 다르다. 배달에 비유하면 내가 주문한 물건을 받는 것과 배달원이 되어 다른 집에 물건을 전달하는 것이 다른 것과 같다.

결국 두 가지를 분리해야 했다. 라우팅에 필요한 조건을 갖추는 일과, 누군가의 결제가 실제로 내 노드를 경유하는 일이다. 전자를 준비했다고 후자가 일정 시간 안에 생기는 것은 아니었다.

Mac과 WSL은 각각 별도 Kubernetes 클러스터와 LND 지갑을 사용했다. 이 글의 UI는 프로젝트의 터미널 운영 도구 `lndops`이며, 각 노드의 RPC 결과를 읽어 진행 상태를 보여준다.

기록도 역할에 따라 다르다.

| 이 노드가 한 일 | 조회 명령 | 확인하는 결과 |
|---|---|---|
| 결제를 시작함 | `lncli listpayments` | 보낸 결제가 성공했는가 |
| 청구서를 발행해 돈을 받음 | `lncli listinvoices` | 해당 청구서가 정산됐는가 |
| 다른 결제를 중간에서 전달함 | `lncli fwdinghistory` | 어떤 채널로 받아 어디로 보냈는가 |

`invoice`는 받을 금액과 목적지를 담은 청구서, `forwarding`은 중간 전달을 뜻한다. 아래에서 실제 조회 코드와 결과를 연결해 본다.

## 내가 보내는 결제와 내가 전달하는 결제

직접 송금은 내 노드가 결제를 시작하거나 끝내는 실습이다. 중계는 다른 결제가 내 노드의 한 채널로 들어와 다른 채널로 나가는 실습이다. `payinvoice`에서 `SUCCEEDED`를 확인했다는 사실만으로 어느 노드가 중계했는지까지 증명할 수는 없다.

중계하려면 들어오는 채널에는 상대가 나에게 보낼 여력이, 나가는 채널에는 내가 다음 노드로 보낼 여력이 필요하다. 각 노드는 연결된 채널의 잔액과 조건부 결제 상태를 갱신한다. C와 D라는 중계 노드가 있다면 C가 D에게 보낼 채널 여력도 있어야 한다.

결제 중인 금액은 HTLC라는 조건부 약속으로 처리된다. 정해진 시간 안에 필요한 비밀값을 제시해야 받을 수 있는 형태다. 최종 수취인의 결제 조건이 충족되면 연결된 결제가 정산되는 구조이므로, 단순히 “먼저 확정 입금받고 나중에 별도 송금한다”는 두 작업으로 보면 맞지 않는다.

## 중계 노드의 돈이 쓰인다는 말을 숫자로 풀어보기

다음은 실측값이 아닌 설명용 경로다. A가 B에게 10 sat를 보내고 C가 1 sat를 중계 수수료로 받는다고 가정한다.

```text
A ── 11 sat ──▶ C ── 10 sat ──▶ B
     A-C 채널       C-B 채널
```

성공적으로 정산되면 C는 A-C 채널에서 자기 몫이 11 sat 늘고, C-B 채널에서는 자기 몫이 10 sat 줄어든다. 두 채널을 합친 C의 몫은 수수료 1 sat만큼 늘어난다. C가 받은 동일한 온체인 거래 출력을 즉시 B에게 전달하는 구조가 아니라, 서로 다른 채널의 배분을 바꾸는 구조다.

따라서 C에게 총자산이 충분하더라도 C-B 채널에서 10 sat를 보낼 여력이 없으면 이 경로의 전달에 참여할 수 없다. A-C 채널에서 들어올 금액이 있다는 사실이 C-B의 부족한 방향별 여력을 자동으로 채워 주지 않는다.

HTLC는 이러한 갱신에 조건을 붙인다. 수취인이 조건을 만족하는 비밀값을 제시하면 역방향으로 정산 근거가 전파되고, 성공하지 못하면 실패 처리 또는 만료 절차를 거친다. 처리 중인 금액은 그동안 다른 결제에 사용할 수 없을 수 있다. 이 때문에 `IN_FLIGHT`를 성공한 입금으로 계산해서는 안 된다. 이 예는 수수료와 잔액 이동을 이해하기 위한 단순화이며 온체인 분쟁 처리의 모든 경우를 나타내지는 않는다.

[BOLT 채널·HTLC 규격](https://github.com/lightning/bolts/blob/master/02-peer-protocol.md)

## 기다리기 전에 시험 경로로 확인하기

Mac과 WSL에 서로 다른 LND 노드를 두고, 외부 peer와의 채널도 사용했다. 실습에서는 자신이 발행한 인보이스를 경로를 돌아 결제하는 방식도 사용했다. 주요 옵션은 다음 의미로 이해했다.

| 옵션 | 실습에서의 역할 |
|---|---|
| `--allow_self_payment` | 자기 노드가 발행한 인보이스를 결제하도록 허용 |
| `--outgoing_chan_id` | 결제를 시작할 송신 채널 제한 |
| `--last_hop` | 수취 직전 peer 제한 |
| `--max_parts=1` | 해당 시험 결제를 한 부분으로 제한 |
| `--fee_limit` | 결제 수수료 상한 지정 |

이 옵션들은 경로의 모든 중간 단계인 hop을 직접 지정한다는 뜻은 아니다. 당시 경로와 채널 잔액에 맞춰 시작·끝 조건을 제한하고, 실제 결과를 따로 확인했다. 채널 ID나 인보이스를 다른 환경에 복사해서 재현할 수 있는 일반 명령으로 싣지 않은 이유도 여기에 있다.

예를 들어 WSL이 발행한 invoice를 WSL이 외부 peer 쪽으로 내보내고 마지막에 Mac을 거쳐 돌아오도록 하면, WSL은 지급자이자 수취인이고 Mac은 중계자 후보가 된다. 반대로 Mac이 시작한 결제가 WSL을 경유하면 WSL에 forwarding 기록이 남는다. 어느 장비에서 명령을 쳤는지가 아니라 경로에서 어떤 역할을 맡았는지가 중요하다.

정확한 중간 경로는 결제 결과의 HTLC route로 확인해야 한다. `outgoing_chan_id`와 `last_hop`만 보고 예상한 모든 중간 노드를 거쳤다고 단정하지 않았다. 공개키는 노드 identity, channel point는 funding 거래의 출력, 숫자형 SCID는 경로에서 채널을 가리키는 짧은 식별자라는 구분도 필요했다. 비슷한 “채널 ID” 표기가 나와도 명령이 요구하는 타입을 확인한다.

## 보낸 쪽과 전달한 쪽의 기록을 따로 확인하기

실습에서는 결제 성공 출력을 확인한 뒤 중계 노드의 forwarding 기록을 확인했다. WSL 화면에 표시된 한 스냅샷에는 최근 24시간 중계 1건과 수수료 1.005 sat, 다음 방향이 나왔다.

```text
Mac peer → WSL 노드 → 외부 peer
전달 금액: 11.000 sat
중계 수수료: 1.005 sat
```

1 sat는 1,000 msat다. 표시된 수수료에는 이 작은 단위가 반영돼 소수가 나올 수 있다. 중요한 것은 숫자가 커졌다는 사실보다, 내가 보려는 노드의 입·출력 채널을 잇는 기록이 생겼다는 점이었다. 이 기록은 실습 트래픽의 경유 증거이며 자연 유입이나 수익성을 증명하지 않는다.

반대로 다른 시점의 Mac 화면이 0건이라고 해서 곧바로 오류는 아니었다. 조회 기간, 조회 노드, 해당 결제에서 맡은 역할이 다르면 결과도 다르다. 그래서 UI에는 대상 노드와 최근 조회 시각을 함께 표시하도록 했다.

## 실제 코드로 결제·수취·중계 기록 읽기

이 글의 조회 대상은 현재 kubeconfig가 가리키는 `lnd-testnet/lnd-0-0`이다. 아래 함수는 뒤에 붙인 lncli 명령을 전달하며, 여기에서 사용하는 조회 명령들은 새 결제를 만들지 않는다.

```bash
export KUBECONFIG="${XDG_STATE_HOME:-$HOME/.local/state}/lnd-ops/kubeconfig"
lnc() {
  kubectl --kubeconfig="$KUBECONFIG" -n lnd-testnet exec lnd-0-0 -c lnd -- \
    lncli --lnddir=/data/.lnd --network=testnet "$@"
}
lnc getinfo | jq '{identity_pubkey, alias}'
lnc listpayments --include_incomplete | jq '.payments[-5:][] | {
  status, value_sat, fee_sat, failure_reason
}'
lnc listinvoices | jq '.invoices[-5:][] | {state, amt_paid_sat}'
START_TIME=$(python3 -c 'import time; print(int(time.time()) - 86400)')
lnc fwdinghistory --start_time="$START_TIME" --max_events=1000 | jq '.forwarding_events[]? | {
  timestamp, chan_id_in, chan_id_out, amt_in_msat, amt_out_msat, fee_msat
}'
```

`listpayments`는 그 노드가 시작한 결제, `listinvoices`는 그 노드가 발행한 청구서의 수취 상태, `fwdinghistory`는 그 노드가 중간에서 전달한 성공 이력을 보는 데 쓴다. 마지막 조회에는 RPC 반환 개수 제한이 있으므로 그 결과 개수만으로 장기간 전체 건수를 확정하지 않는다. lab의 UI는 한 번에 최대 50,000건을 요청하고 상한에 걸리면 일부 기록임을 표시한다.

위 결제·invoice 명령도 반환된 목록의 마지막 다섯 항목을 보여주는 예시이며, 페이지 전체를 순회하는 감사 명령은 아니다.

성공한 결제의 실제 경로는 다음처럼 따로 펼쳐 본다. 반환된 성공 결제 중 생성 시각이 가장 최근인 항목을 고르는 예시다. 이것이 원하는 시험 결제인지는 금액과 실습 시각으로 확인해야 한다.

```bash
lnc listpayments --include_incomplete | jq '
  [.payments[] | select(.status == "SUCCEEDED")]
  | sort_by(.creation_time_ns | tonumber)
  | last
  | select(. != null)
  | {creation_time_ns, value_msat, fee_msat,
     attempts: [.htlcs[]? | select(.status == "SUCCEEDED") | {
       attempt_id, attempt_time_ns, resolve_time_ns,
       hops: [.route.hops[] | {pub_key, chan_id, amt_to_forward_msat, fee_msat}]
     }]}'
```

홉별 공개키와 채널 식별자를 보면 예상한 중계 노드가 경로에 있는지 확인할 수 있다. `value_msat`와 `fee_msat`는 1 sat의 1,000분의 1 단위이므로, 소수 sat 수수료를 비교할 때 정수 sat로 잘라 읽는 실수를 피할 수 있다. 전체 경로를 공개 게시물에 옮길 필요는 없으므로 여기에는 실측 공개키를 싣지 않았다.

`chan_id_in`과 `chan_id_out`은 숫자형 채널 식별자다. 이 lab의 LND v0.21.3-beta CLI는 `listchannels`에서 그 숫자를 `scid`로 출력하고 `chan_id`에는 다른 64자리 식별자를 넣으므로, 여기서는 `scid`와 대응시켜 상대를 찾는다. 필드명이 비슷하다고 64자리 값을 송신 채널 옵션에 넣지 않는다.

[해당 버전의 CLI 출력 변환](https://raw.githubusercontent.com/lightningnetwork/lnd/v0.21.3-beta/cmd/commands/commands.go) 서로 다른 거래의 성공 출력을 한 번씩 발견한 것만으로 하나의 시험 결제를 증명할 수는 없다. 통제한 실습에서는 결제 시각·금액·경로와 송신·수신 결과를 대조한다.

forwarding 기록만으로 원래 invoice를 그대로 읽을 수 있다는 뜻도 아니다.

UI의 최근 24시간 0건은 그 기간에 확인된 중계가 없다는 뜻이다. 조회 실패, 다른 노드를 보고 있음, 실제 0건은 다르게 표시해야 했다. 그래서 최근 조회 시간과 대상 identity를 함께 표시하고, 재조회 실패 때는 이전 값을 최신 정상값처럼 보여주지 않도록 구분했다.

## 블록 탐색기에 모든 송금이 나오지는 않았다

Lightning 결제마다 Bitcoin transaction이 하나씩 생기는 구조는 아니다. 채널을 열거나 닫는 온체인 거래와, 채널 안에서 갱신되는 결제 상태를 구분해야 한다. 따라서 개별 중계를 온체인 탐색기에서 찾는 대신 LND의 결제·invoice·forwarding 기록을 사용했다.

채널과 HTLC의 연결은 [BOLT 소개](https://github.com/lightning/bolts/blob/master/00-introduction.md)에서 확인할 수 있다.

온체인에 “지갑 잔액 숫자만 올라간다”고 이해하는 것도 정확하지 않다. Bitcoin에는 거래와 출력이 기록된다. 채널 개설 거래는 funding 출력을 만들고, 채널 종료 거래는 정산에 맞는 출력을 만든다. 그 사이의 Lightning 상태 갱신마다 별도 거래를 채굴하는 것은 아니다. 중계도 각각의 채널 상태를 갱신하므로 개별 중계 한 건에 대응하는 온체인 transaction ID가 반드시 생기지 않는다.

[BOLT 거래 형식](https://github.com/lightning/bolts/blob/master/03-transactions.md)

## 준비가 됐는데 자연 중계가 없는 이유

다른 송신자가 내 노드를 경유하는 경로를 선택해야 자연 중계가 생긴다. 내 노드가 켜져 있고 공개 채널이 여러 개라는 조건만으로 결제를 만들어 낼 수는 없다. 수취 목적지까지 이어지는 경로, 금액, 수수료 정책, 각 방향의 유동성과 상대의 상태가 함께 작용한다.

따라서 10분 동안 0건이었다는 관측만으로 UI가 잘못됐다고 결론 내리기도, testnet 사용자가 아무도 없다고 결론 내리기도 어렵다. 통제한 시험 결제가 성공하면 특정 시점·금액·경로의 전달 능력은 확인할 수 있지만, 이후 자연 유입 빈도는 별개다.

또 같은 공유기 아래 Mac과 WSL이 연결됐다는 결과는 외부 인터넷에서 내 공개 P2P 주소로 접속할 수 있다는 증거가 아니다. 광고한 URI가 있다는 것, 실제 연결이 있다는 것, 독립적인 외부망에서 그 identity로 접속했다는 것을 각각 확인해야 했다.

## 이번에 확인한 것과 아직 남은 것

이번에는 통제한 결제가 중계되는 결과를 얻었다. 하지만 이후 WSL 운영 화면에는 라우팅 정책 미충족과 외부 P2P 접속 미검증이 남았다. 한 번의 forwarding 성공을 전체 운영 준비 완료로 바꾸어 쓰면 안 됐다.

이 경험 때문에 진행 화면도 동기화, 채널, 정책·유동성, 실제 중계, 외부 접속을 따로 보여주도록 바뀌었다. “10분 기다렸으니 한 건쯤 들어와야 한다”는 기대 대신, 검증하려는 조건에 맞는 시험 결제를 구성하고 그 노드의 기록을 확인하게 됐다.

관련 구현: [Router 운영 runbook](../phase2-router-runbook.md), [실시간 이력 UI](../../ops/start). 다음 편에서는 유동성을 바꾸려고 시도한 Loop Out이 왜 별도 문제였는지 다룬다.
