# 신호에서 판단까지

> 각 LND·Kubernetes 지표를 사용자 영향, alert, runbook, kagent 판단과 연결한다

신호에서 판단까지



좋은 대시보드는 수치를 많이 보여주는 화면이 아니라 **운영자가 다음 행동을 결정하는 데 필요한 상관관계**를 보존한다. 이 프로젝트는 LND 자체 exporter, lndmon, 제한된 custom collector, Kubernetes와 host 신호를 함께 사용한다.



왜 이 값들을 보는가

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

임계값은 운영 목표의 표현이다

- **10,000 sats liquidity:** 데모에서 증명하려는 송수신 목표다. 보편적 운영 임계값이 아니다.
- **결제 실패 3회/1h:** 한 번의 라우팅 실패보다 반복되는 사용자 영향을 잡기 위한 초기 기준이다.
- **PVC·guest disk 10%:** cleanup과 확장 판단을 위한 여유 구간이다. 증가율 기반 예측은 향후 과제다.
- **SCB 24h:** 백업 부재·불일치와 장기 미갱신을 묶은 초기 운영 정책이다.
- **TLS 30일:** 수동 회전 runbook을 수행할 시간을 확보한다.

상관관계와 억제

wallet이 `LOCKED` 또는 `NON_EXISTING`이면 sync, channel, lndmon 경보가 연쇄적으로 생길 수 있다. root cause가 명확한 상태에서 파생 경보를 억제해야 운영자가 같은 사건을 여러 장애로 오해하지 않는다. 반대로 wallet-state collector의 scrape가 실패했으면 `LOCKED=0`을 정상으로 해석하지 않고 별도 unavailable alert를 낸다.

대시보드 분리

| 화면 | 운영 질문 |
| --- | --- |
| Overview | 지금 노드가 전체적으로 서비스 가능한가? |
| Node and Channels | sync, peer, channel 중 어디가 막혔나? |
| Payments and Liquidity | 어느 방향의 결제 능력과 품질이 떨어졌나? |
| Kubernetes | Pod, node, PVC 중 인프라 원인은 무엇인가? |
| Security | 정책 적용과 runtime event가 정상인가? |
| Backup and Recovery | SCB와 복구 준비가 최신인가? |

데이터 최소화

payment hash, invoice 내용, macaroon, peer identity를 custom metric label이나 LLM 입력에 넣지 않는다. label cardinality와 정보 노출을 함께 줄인다. collector는 집계값과 상태만 내보낸다.

구현 근거

- `charts/monitoring-rules.yaml`: 16개 운영 alert와 runbook 연결
- `charts/dashboards/`: 여섯 개 Git-provisioned dashboard
- `collector/payment_metrics.py`: 집계된 결제·wallet·SCB·TLS 지표
- `docs/observability-plan.md`: 신호 선택과 알려진 공백
- Prometheus alerting rules

읽기 전용 관찰



알려진 공백

- 취소된 invoice는 수신 실패가 아니므로 receive-failure 관측은 미완성이다.
- PC나 K3s 자체가 멈추면 내부 Prometheus/Alertmanager도 알릴 수 없다.
- 임계값은 현재 데모 목표와 관측량에 맞춘 초기값이며 실제 mainnet SLO가 아니다.

점검 문제
왜 `up == 0`과 업무 지표 0을 구분해야 하는가?업무 지표 0은 정상 상태일 수 있지만 `up == 0`이면 그 값을 관측하지 못한 것이다. 관측 실패를 정상으로 해석하면 false negative가 생긴다.
incoming liquidity alert를 채널 개설 직후 바로 켜면 왜 잡음이 될 수 있는가?로컬 자금으로 연 채널은 처음에 outbound 위주다. inbound를 만들기 전 낮은 incoming liquidity는 설계된 초기 상태다.

면접 질문
> 결제 실패율 alert를 설계할 때 낮은 트래픽, 라우팅 실패의 정상 변동, 방향별 liquidity를 어떻게 함께 다룰 것인가?
