---
title: 신호에서 판단까지
description: 각 LND·Kubernetes 지표를 사용자 영향, alert, runbook, kagent 판단과 연결한다
versions: lndmon 0.2.15 · kube-prometheus-stack 91.4.1
platforms: macOS arm64 · Windows WSL2 amd64
verified: 2026-09-24
commit: 841692b
status: 실제 환경 검증됨
scope: regtest · testnet
---

# 신호에서 판단까지

좋은 대시보드는 수치를 많이 보여주는 화면이 아니라 **운영자가 다음 행동을 결정하는 데 필요한 상관관계**를 보존한다. 이 프로젝트는 LND 자체 exporter, lndmon, 제한된 custom collector, Kubernetes와 host 신호를 함께 사용한다.

<ClientOnly>
  <MermaidDiagram label="운영 목표가 지표, alert, runbook, 제한된 자동 대응으로 변환되는 과정" :code="`flowchart LR
    U[운영 목표] --> S[signals]
    S --> Q[PromQL correlation]
    Q --> A[alert + duration]
    A --> R[versioned runbook]
    R --> K[kagent diagnosis]
    K --> G{policy gate}
    G -->|read / probe restart| X[action]
    G -->|wallet / funds / PVC| H[human approval]
    X --> V[health verification]
    H --> V
  `" />
</ClientOnly>

## 아주 쉽게 비유하면: 체온계가 꺼진 것은 0도가 아니다

체온계에 숫자가 나오면 그때 잰 온도를 알 수 있다. 그런데 건전지가 빠져 화면이 꺼졌다면 체온이 0도라는 뜻일까? 아니다. 지금은 재지 못한 것이다. 한참 전에 잰 숫자도 지금 온도와 같다고 단정할 수 없다.

**실제 시스템에 연결하면:** 지표의 0, 수집 실패, 오래된 표본을 구분해야 한다. Prometheus는 시간에 따른 표본을 모으고 대시보드는 이를 보여 준다. 다만 체온계 하나로 사람의 모든 상태를 알 수 없듯, 지표 하나로 결제 가능 여부 전체를 알 수는 없다.

## 배경 1: Prometheus가 저장하는 것은 시간에 따른 표본이다

Prometheus에서 시계열은 지표 이름과 label 조합으로 식별된다. 예를 들어 같은 지표라도 노드 label이 다르면 별도 시계열이다. 각 시계열에는 수집 시각과 값의 표본이 쌓인다. exporter는 LND나 Kubernetes의 상태를 읽어 수집 가능한 형식으로 내놓고, Prometheus가 이를 주기적으로 가져온다. Grafana는 저장된 데이터를 질의해 보여준다. [Prometheus 구조](https://prometheus.io/docs/introduction/overview/)

이 흐름에는 지연이 있다. 장애가 발생한 시점, 다음 scrape 시점, 경보 평가 시점, 알림 전송 시점은 같지 않다. 따라서 화면에 아직 경보가 없다는 사실만으로 방금 일으킨 장애가 없다고 결론 내릴 수 없다. 반대로 오래된 표본을 보고 이미 복구된 상태를 장애라고 해석할 수도 있다. 그래프를 볼 때 값과 함께 시간 범위를 확인하는 이유다.

예를 들어 scrape가 30초, rule 평가가 30초인 가상 설정에서 `for: 5m`이면 장애 발생 후 정확히 5분에 메시지가 도착한다고 보장할 수 없다. 최초 관측과 평가까지 기다리는 시간, 알림 그룹화와 전달 시간이 더해질 수 있다. 이 숫자는 설명용이며 프로젝트의 실제 주기라고 주장하는 값이 아니다.

## 배경 2: counter와 gauge를 혼동하면 계산이 틀어진다

**counter**는 누적 횟수처럼 증가하다 프로세스 재시작 등으로 초기화될 수 있는 값이다. **gauge**는 현재 잔액이나 활성 채널 수처럼 증가와 감소가 모두 가능한 값이다. **histogram**은 관측값을 구간별로 집계해 분포를 표현한다. 지연시간 평균이 같아도 일부 요청만 매우 느릴 수 있으므로 분포가 유용하다. [Prometheus 지표 유형](https://prometheus.io/docs/concepts/metric_types/)

학습용 counter가 5분 동안 100에서 130으로 늘고 reset이 없었다면 증가량은 30, 평균 속도는 초당 0.1회다. 실제 PromQL의 `rate()`는 counter reset과 표본 간격을 고려한다. 반면 현재 채널 잔액이 100,000에서 90,000으로 줄었다는 사실을 counter reset처럼 처리하면 의미가 달라진다.

현재 payment collector의 “최근 1시간 실패 수”는 최근 1시간에 생성된 결제 중 현재 `FAILED` 상태인 건수를 나타내는 gauge다. 실패 발생 시각이나 개별 HTLC 시도 횟수 기준이 아니다. 시간이 지나 실패 기록이 창 밖으로 빠지면 새로운 성공이 없어도 감소할 수 있다. 이 값에 counter용 `rate()`를 붙여 실패율이라고 부르지 않는다. 실패율이 필요하면 같은 기간과 같은 집계 단위의 실패·전체 건수를 정의하고, 전체 건수가 0인 경우도 별도로 처리해야 한다.

## 배경 3: 0, 수집 실패, 시계열 부재는 다르다

inactive channel 수가 0이라는 표본은 exporter가 값을 내놓았고 그 시점에 비활성 채널이 없다는 뜻이다. scrape가 실패한 경우에는 그 값을 새로 읽지 못한 것이다. target 자체가 발견되지 않으면 예상한 시계열이 아예 없을 수도 있다. 이 셋을 모두 초록색 0으로 표시하면 관측 장애가 정상 상태처럼 보인다.

이 때문에 application 지표 옆에 target 상태와 수집 경로를 함께 본다. `up=1`도 exporter의 scrape 성공을 뜻할 뿐 LND 결제 성공을 보장하지 않는다. 지갑 잠금처럼 이미 알려진 상태가 다른 경보를 여러 개 일으키면 원인 경보를 우선하도록 억제를 설계하되, 수집 자체가 사라지는 공백까지 가려서는 안 된다.

label 설계도 운영 비용이다. payment hash처럼 결제마다 달라지는 식별자를 label로 넣으면 시계열 수가 빠르게 늘고 민감한 활동 이력도 노출된다. 이 프로젝트는 집계 지표로 상태를 보고 필요한 상세 확인은 접근을 제한한 증거에서 수행하는 방향을 사용한다.


## “결제가 안 된다”에서 관측 순서를 도출하기

사용자가 결제를 보내지 못한다고 할 때 CPU 그래프부터 보는 것은 좋은 출발점이 아닐 수 있다. wallet이 잠겼는지, 체인 sync가 끝났는지, 채널이 active인지, 보낼 방향의 유동성이 있는지를 먼저 확인하면 원인 범위를 빠르게 줄일 수 있다. CPU·메모리·디스크는 그 조건이 왜 깨졌는지 설명하는 인프라 근거로 연결한다.

데이터 생산자도 다르다. lndmon은 LND에서 읽은 채널과 체인 신호를, custom collector는 결제 결과의 시간 구간 집계와 wallet·백업·인증서 정보를, Kubernetes exporter는 리소스 상태를 제공한다. producer가 달라서 갱신 시점과 실패 방식도 다르다. 대시보드의 두 값이 모순되어 보이면 어떤 producer가 최근에 성공적으로 수집했는지부터 확인한다.

## 왜 이 값들을 보는가

| 질문 | 신호 | 함께 볼 신호 | 판단 |
| --- | --- | --- | --- |
| 노드가 RPC를 받을 준비가 됐나? | wallet state | scrape up | `LOCKED`와 collector 장애를 구분 |
| 체인을 따라가고 있나? | `lnd_chain_synced` | wallet state, block age, peer | 잠긴 wallet에서 파생 경보 억제 |
| 채널을 쓸 수 있나? | active/inactive channel | peer, pending HTLC | peer 단절과 채널 자체 문제를 구분 |
| 목표 금액을 보낼/받을 수 있나? | 방향별 bandwidth 합 | active channel | capacity 대신 방향별 가능성 판단 |
| 결제 품질이 나빠졌나? | trailing-hour outcome | latency, fee, liquidity | 일시 실패와 반복 실패 분리 |
| 데이터를 잃을 위험이 있나? | PVC/guest disk free | node pressure | 볼륨 부족과 host disk 부족 분리 |
| 채널 복구 준비가 됐나? | SCB current/age | source present | 존재만이 아니라 최신성 판단 |
| 관측 자체가 고장 났나? | scrape `up` | Prometheus Pod | “정상”과 “보이지 않음” 구분 |

## 임계값은 운영 목표의 표현이다

- **10,000 sats liquidity:** 데모에서 증명하려는 송수신 목표다. 보편적 운영 임계값이 아니다.
- **결제 실패 3회/1h:** 한 번의 라우팅 실패보다 반복되는 사용자 영향을 잡기 위한 초기 기준이다.
- **PVC·guest disk 10%:** cleanup과 확장 판단을 위한 여유 구간이다. 증가율 기반 예측은 향후 과제다.
- **SCB 24h:** 백업 부재·불일치와 장기 미갱신을 묶은 초기 운영 정책이다.
- **TLS 30일:** 수동 회전 runbook을 수행할 시간을 확보한다.

## 상관관계와 억제

wallet이 `LOCKED` 또는 `NON_EXISTING`이면 sync, channel, lndmon 경보가 연쇄적으로 생길 수 있다. root cause가 명확한 상태에서 파생 경보를 억제해야 운영자가 같은 사건을 여러 장애로 오해하지 않는다. 반대로 wallet-state collector의 scrape가 실패했으면 `LOCKED=0`을 정상으로 해석하지 않고 별도 unavailable alert를 낸다.

## 채널 경보의 PromQL을 문장으로 읽기

현재 rule의 핵심은 아래와 같다. 이것은 설명용으로 namespace 필터를 생략한 발췌이며, 실제 식은 연결된 rule 파일에서 확인한다.

```text
((lnd_channels_inactive_total > 0)
  and on (namespace, service) (up{job="lndmon"} == 1))
  unless on (namespace, service)
    (lnd_ops_wallet_state{state=~"LOCKED|NON_EXISTING"} == 1)
```

첫 조건은 비활성 채널이 있다는 사실이다. 두 번째 조건은 같은 namespace와 service의 lndmon scrape가 성공했음을 확인한다. 마지막 조건은 잠금 또는 미생성 wallet로 설명되는 대상을 제외한다. `on`은 어떤 라벨이 같은 대상을 뜻하는지 지정하므로 라벨 배치가 바뀌면 쿼리의 상관관계도 다시 검증해야 한다.

rule에 붙은 `for: 5m`은 조건이 지속되는 시간을 요구한다. 알림이 최대 5분 안에 반드시 온다는 보장은 아니다. scrape 간격, 평가 간격과 Alertmanager 전달 설정도 영향을 준다. 실제 fault 실습에서 전체 전달 경로를 시험하는 이유다.

`up == 0`은 등록된 target의 scrape 실패를 찾지만 target 자체가 사라져 시계열이 없어진 모든 경우를 포괄하지는 않는다. `absent` 같은 부재 검사와 기대 target 목록의 비교가 필요한 경우가 있다. 현재 경보가 모든 관측 공백을 감지한다고 설명하지 않는다.

## 숫자를 경보로 바꾸기 전에 묻는 질문

백업 나이가 기준을 넘으면 새 백업을 만들 필요가 있을 수 있지만, 원본 SCB가 존재하는지와 이전 기록이 일치하는지도 함께 본다. 디스크 여유율은 비슷해 보여도 PVC 부족과 guest root 부족의 정리 대상이 다르다. LND 데이터를 지우는 조치를 일반 disk cleanup으로 제안해서는 안 된다.

결제 지표의 `1h` 집계는 최근 한 시간의 결과를 나타내며 단조 증가 counter가 아니다. 그 값에 무조건 `rate()`를 적용하면 의도한 실패율과 달라질 수 있다. 지표 이름과 타입, 계산 구간을 collector 코드에서 확인한 뒤 쿼리를 작성해야 한다.

## 대시보드 분리

| 화면 | 운영 질문 |
| --- | --- |
| Overview | 지금 노드가 전체적으로 서비스 가능한가? |
| Node and Channels | sync, peer, channel 중 어디가 막혔나? |
| Payments and Liquidity | 어느 방향의 결제 능력과 품질이 떨어졌나? |
| Kubernetes | Pod, node, PVC 중 인프라 원인은 무엇인가? |
| Security | 정책 적용과 runtime event가 정상인가? |
| Backup and Recovery | SCB와 복구 준비가 최신인가? |

## 데이터 최소화

payment hash, invoice 내용, macaroon, peer identity를 custom metric label이나 LLM 입력에 넣지 않는다. label cardinality와 정보 노출을 함께 줄인다. collector는 집계값과 상태만 내보낸다.

## 구현 근거

- [`charts/monitoring-rules.yaml`](https://github.com/s1ns3nz0/lnd-ops/blob/master/charts/monitoring-rules.yaml): 16개 운영 alert와 runbook 연결
- [`charts/dashboards/`](https://github.com/s1ns3nz0/lnd-ops/tree/master/charts/dashboards): 여섯 개 Git-provisioned dashboard
- [`collector/payment_metrics.py`](https://github.com/s1ns3nz0/lnd-ops/blob/master/collector/payment_metrics.py): 집계된 결제·wallet·SCB·TLS 지표
- [`docs/observability-plan.md`](https://github.com/s1ns3nz0/lnd-ops/blob/master/docs/observability-plan.md): 신호 선택과 알려진 공백
- [Prometheus alerting rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)

## 읽기 전용 관찰

```sh
ops/verify-monitoring --profile regtest
ops/verify-dashboards
kubectl -n lnd-monitoring get prometheusrule lnd-ops-infrastructure -o yaml
```

## 알려진 공백

- 취소된 invoice는 수신 실패가 아니므로 receive-failure 관측은 미완성이다.
- PC나 K3s 자체가 멈추면 내부 Prometheus/Alertmanager도 알릴 수 없다.
- 임계값은 현재 데모 목표와 관측량에 맞춘 초기값이며 실제 mainnet SLO가 아니다.

## 점검 문제
<details class="quiz"><summary>왜 `up == 0`과 업무 지표 0을 구분해야 하는가?</summary>업무 지표 0은 정상 상태일 수 있지만 `up == 0`이면 그 값을 관측하지 못한 것이다. 관측 실패를 정상으로 해석하면 false negative가 생긴다.</details>
<details class="quiz"><summary>incoming liquidity alert를 채널 개설 직후 바로 켜면 왜 잡음이 될 수 있는가?</summary>로컬 자금으로 연 채널은 처음에 outbound 위주다. inbound를 만들기 전 낮은 incoming liquidity는 설계된 초기 상태다.</details>

### 면접 질문
> 결제 실패율 alert를 설계할 때 낮은 트래픽, 라우팅 실패의 정상 변동, 방향별 liquidity를 어떻게 함께 다룰 것인가?

## 이 설계가 정해진 과정

[실제 결제 데이터부터 통합하기로 한 결정](/decisions/#adr-004). 대화에서 정한 방향과 현재 구현·보류 범위를 함께 읽는다.
