# 지표에서 경보로: lndmon과 PrometheusRule의 역할

> Lightning 노드 운영 회고 8편 · Phase 5 후반 · 2026-09-28 Mac 수동 실습 기준

온도계가 30도를 보여주는 것과 “30도 이상이면 알려줘”라고 정하는 것은 다르다. 지표는 온도계의 숫자, 경보 규칙은 언제 알려줄지 적은 조건이다. Grafana 화면과 경보 규칙도 따로 설정한다.

```text
프로그램이 숫자를 제공
  → Prometheus가 기록
  → 규칙이 “문제가 계속되는가?” 판단
  → Alertmanager가 경보를 받아 전달 설정에 따라 처리
```

이 lab은 PrometheusRule이라는 Kubernetes 리소스에 조건을 적는다. Prometheus Operator는 그 리소스를 읽어 Prometheus가 사용할 규칙으로 연결하는 관리자다. 이름은 길지만 “Kubernetes에 적은 조건을 실제 검사 프로그램에 전달한다”는 역할로 보면 된다.

## 숫자·화면·경보 조건을 나누어 보기

| 대상 | 이 lab의 파일 또는 소스 | 역할 |
|---|---|---|
| 대시보드 | `charts/dashboards/*.json` → ConfigMap | 그래프 배치와 PromQL 조회식 |
| 실제 지표 | LND·lndmon·별도 collector·Kubernetes exporter | 관측한 값을 Prometheus에 제공 |
| 알림 규칙 | `charts/monitoring-rules.yaml` → PrometheusRule | 조건과 지속 시간으로 경보 판단 |

PrometheusRule은 Prometheus Operator가 처리하는 사용자 정의 리소스다. YAML을 등록하면 선택 조건에 맞는 규칙을 Operator가 Prometheus 설정에 반영한다. Kubernetes에 리소스가 있다는 사실과 Prometheus가 실제로 평가하고 있다는 사실은 나눠 확인해야 했다.

Helm 차트가 기본 알림을 제공할 수도 있다. 이 저장소의 values는 `defaultRules.create: false`로 설정하고 lab용 규칙을 따로 정의한다. 다른 배포의 모든 기본 규칙이 반드시 꺼져 있다는 주장으로 확대하지 않고, 실행 중인 환경에서는 실제 values와 Rules 화면을 함께 봤다.

## lndmon은 숫자를 만들고 규칙은 조건을 판단한다

lndmon은 LND의 상태를 수집하고 Prometheus·Grafana와 함께 사용하는 도구이며 기본 대시보드도 제공한다. 이 lab은 그 지표를 재사용하고, 별도의 지갑·결제·백업 관측과 Kubernetes 지표를 함께 연결한다. lndmon의 범위는 [공식 README](https://github.com/lightninglabs/lndmon#what-is-this)에서 확인했다.

가령 `lnd_channels_inactive_total`이라는 값이 있다고 하자. lndmon은 비활성 채널 수를 관측하고, 우리 규칙은 그 상태를 언제 문제로 볼지 정한다.

```text
지표: 비활성 채널이 존재한다
조건: 정상 수집 중이고, 지갑 잠금 등 별도 상태를 제외한다
지속 시간: 5분
결과: 비활성 채널 경고
```

실제 YAML은 지갑 잠금으로 인해 파생되는 중복 경보를 줄이기 위한 조건도 포함한다. 위 설명은 이해를 위한 요약이며 복사해서 적용할 완전한 규칙은 아니다.

## 우리가 추가로 세는 숫자는 무엇인가

LND의 채널 상태뿐 아니라 최근 한 시간의 결제 결과, 지갑 잠금 상태, 백업 파일의 최신 여부와 TLS 만료 시각을 운영 화면에 연결했다. 예를 들어 `lnd_ops_wallet_state`는 지갑이 잠겨 있는 상황과 단순 scrape 오류를 구분하는 데 쓴다. 지갑이 잠겨 RPC를 사용할 수 없다면 채널 지표가 사라진 원인을 먼저 설명해야 하기 때문이다.

백업 지표도 의미를 좁혀 읽는다. SCB는 Static Channel Backup, 즉 채널 복구에 사용하는 정적 채널 백업이다. 최신 채널 상태 전체를 복사한 파일과는 다르다. `lnd_ops_scb_backup_current`가 나타내는 것은 기록한 사본과 현재 SCB의 일치 여부다. 그것만으로 seed 보관, 복호화 암호 확보, 외부 보관 사본과 실제 복구 성공이 모두 확인되는 것은 아니다.

운영 지표는 그 지표를 만드는 검사 범위만 증명한다.

사용자 정의 metric에 이름이 붙었다고 실제 Lightning 프로토콜 상태가 새로 생기는 것도 아니다. collector가 어떤 RPC와 파일을 읽어 어떤 단위·시간 범위로 계산했는지까지 알아야 그 값을 올바르게 사용할 수 있다.

## 실제 경보 YAML을 한 줄씩 읽기

다음은 현재 저장소의 Pod 준비 상태 규칙이다. 설명을 위해 상위 `groups` 구조를 생략하고 규칙 하나만 발췌했다.

```yaml
- alert: LndOpsPodNotReady
  expr: kube_pod_status_ready{namespace=~"lnd-regtest|lnd-testnet",condition="false"} == 1
  for: 1m
  labels:
    severity: warning
  annotations:
    summary: "LND namespace Pod {{ $labels.namespace }}/{{ $labels.pod }} is not Ready"
    runbook: docs/runbooks/pod-not-ready.md
```

`expr`는 두 LND namespace에서 Ready가 false인 Pod를 고른다. `namespace=~"lnd-regtest|lnd-testnet"`의 `=~`는 패턴 비교이고, 여기서는 두 이름 중 하나와 일치하는 대상을 고른다. `== 1`은 그 상태 지표가 1인지 비교한다. `for: 1m`은 한 번의 일시적 전환만으로 바로 경고하지 않고 조건이 이어지는지 보겠다는 선택이다.

`severity`는 이후 분류·전달에 사용할 label이며, `summary`는 사람이 읽는 메시지다. annotation 안의 템플릿은 경보 문맥의 namespace와 Pod 이름을 넣는다.

1분을 어떻게 해석할지 설명용 시간표로 보자.

| 시간 | 관측한 상태 | 의미 |
|---|---|---|
| 10:00:00 | Ready가 false로 관측됨 | 조건 충족을 기다리기 시작 |
| 10:00:30 | 계속 false | 아직 1분 미만이므로 Pending |
| 10:01:00 이후 평가 | 같은 조건이 1분 이상 지속 | Firing 가능 |

실제 시각은 수집·평가 간격에 따라 달라진다. 중간에 조건이 사라지면 계속 실패한 1분으로 세지 않는다. 이 표는 실습에서 측정한 시간표가 아니라 `for: 1m`를 이해하기 위한 예시다.

이 식은 Pod가 관측되고 Ready false일 때를 다룬다. 대상 namespace의 모든 Pod가 사라졌거나 kube-state-metrics 자체가 수집되지 않는 경우까지 이 규칙 하나가 잡는 것은 아니다. 그 경우는 누락·수집 상태를 별도로 확인해야 한다.

`runbook`은 실행할 명령이 아니라 사람이 참고할 대응 문서 위치다. 이 경우에는 대상 Pod의 Events, 컨테이너별 state, restart count와 로그부터 확인한다. 스케줄링 실패라면 자원·볼륨을, 이미지 시작 실패라면 이미지와 아키텍처를, 실행 후 실패라면 해당 컨테이너 로그를 확인한다. 경보를 받았다는 이유만으로 지갑을 새로 만들거나 PVC를 지우는 작업으로 연결하지 않는다.

## 몇 분 기다리고 얼마 이하에서 알려줄까

현재 저장소의 규칙 중 일부는 다음과 같다.

| 조건 | 지속 시간 |
|---|---|
| LND Namespace의 Pod가 Ready가 아님 | 1분 |
| LND PVC의 남은 공간이 10% 미만 | 5분 |
| 활성 채널의 총 송신 여력이 10,000 sat 미만 | 5분 |
| 최근 한 시간 실패 결제 관측 수가 3건 이상 | 5분 |

10,000 sat는 Lightning 프로토콜이 정한 필수 잔액이 아니라 lab의 시연 기준이다. 이 임계값이 적절한지는 실제로 운영하려는 채널 규모와 목적에 따라 바뀐다. 수집이 실패하거나 지표가 없는 상황을 단순히 조건 미충족으로 읽지 않는 것도 중요하다.

규칙을 운영 행동으로 풀면 다음과 같다. 경보 이름을 외우는 것보다 어떤 증거를 추가로 볼지 정하는 데 목적이 있다.

| 규칙이 가리키는 상황 | 다음에 확인할 내용 |
|---|---|
| 지갑 잠금 | 기존 지갑인지, 마지막 재시작 이후 unlock이 필요한지 |
| 체인 동기화 미완료가 지속됨 | LND 로그·backend 연결·최근 블록 상태 |
| 비활성 채널 | 상대 peer 연결, pending 상태, 일시적 재시작 여부 |
| 송신·수신 여력 부족 | 채널별 방향 잔액과 실제 시험 금액 |
| 반복 결제 실패 | payment 최종 상태·시도별 실패 코드·경로 |
| PVC·게스트 디스크 부족 | 어느 볼륨·마운트가 부족한지와 실제 사용량 |
| SCB 사본이 오래됨 | 현재 채널 변화와 백업 기록의 일치·최근 검증 시각 |

여기서 “체인 동기화 정체”라는 경보 이름도 식보다 넓게 읽으면 안 된다. 현재 식은 `lnd_chain_synced == 0`이 일정 시간 지속되는지를 본다. 정상 초기 동기화가 오래 걸리는 경우와 완전히 멈춘 경우를 이 값 하나로 구별하지는 않는다.

최근 한 시간 실패 결제 값은 지금을 기준으로 과거 한 시간을 움직여 가며 세는 값이다. 정확히는 collector가 최근 한 시간 안에 생성된 결제를 골라 현재 상태가 FAILED인 항목을 센다. 오래전에 생성된 결제가 방금 실패했다고 반드시 이 값에 포함되는 것은 아니다. 그것에 `for: 5m`를 붙였다고 최근 5분에 세 번 실패했다는 뜻은 아니다.

최근 한 시간 창에서 3건 이상이라는 조건이 5분간 계속 평가되는 것이다.

합산 유동성 규칙도 마찬가지다. 활성 채널 합계가 10,000 sat 이상이면 경고 조건에서 벗어날 수 있지만, 특정 peer 방향이나 특정 목적지까지 10,000 sat를 전달할 수 있는지는 별개다. 대시보드와 경보의 숫자를 실제 결제 가능성으로 과장하지 않기 위해 이 범위를 명시했다.

## 규칙이 들어갔는지 실제로 작동하는지 확인하기

Mac에서는 다음 조회로 기존 `lnd-monitoring` namespace의 `lnd-ops-infrastructure` 리소스를 확인했다.

```bash
kubectl get prometheusrules -A
```

Prometheus UI에서도 Rules와 Alerts를 확인했고, 이번 확인에서는 평가 오류나 특별히 조사할 알림이 없었다. 알림 상태의 의미는 다음과 같이 이해했다.

- `Inactive`: 해당 규칙의 활성 조건에 해당하지 않음.
- `Pending`: 조건은 충족됐지만 `for` 지속 시간을 기다리는 중.
- `Firing`: 설정된 지속 조건을 충족한 상태.

`for`는 조건이 지속되는 시간을 평가하는 설정이다. 실제 동작은 [Prometheus 알림 규칙 문서](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)와 대조했다. `Inactive`만으로 서비스 전체가 정상이라고 말하지는 않았다. 지표가 수집되고 있는지도 별도로 확인해야 한다.

규칙이 등록됐는데 Rules 화면에 없다면 CRD 존재 여부만 반복해서 볼 일이 아니다. Prometheus 리소스의 `ruleSelector`와 `ruleNamespaceSelector`가 그 PrometheusRule을 선택하는지, 리소스의 namespace와 label이 일치하는지 확인한다. 이 저장소의 규칙에는 `release: lnd-ops-monitoring` label이 붙어 있다.

```bash
kubectl -n lnd-monitoring get prometheus
kubectl -n lnd-monitoring get prometheus -o yaml
kubectl -n lnd-monitoring get prometheusrule lnd-ops-infrastructure -o yaml
```

이 명령은 실제 Mac에서 확인한 namespace를 사용한다. 새 설치의 기본 namespace와 다를 수 있다. 출력에서는 선택 조건과 규칙 내용을 비교하고, Prometheus UI에서는 rule health와 평가 오류를 확인한다. `Firing` 상태라도 실제 외부 메시지 도착까지 확인한 것은 아니다.

## 경보 발생과 휴대폰 알림 도착은 다르다

현재 values의 Alertmanager는 `local-only` receiver를 사용한다. `group_by`는 `alertname`과 `namespace`이며, 메일·메신저·웹훅 수신 설정은 없다. 따라서 경보가 발생했을 때 Alertmanager에서 볼 수는 있어도, 이 설정만으로 휴대폰에 알림이 온다고 기대할 수 없다.

```text
규칙 조건 충족
  → Pending
  → 지속 조건 충족 뒤 Firing
  → Alertmanager가 수신·그룹화
  → 외부 receiver가 구성돼 있을 때 실제 전달
```

마지막 단계의 성공을 증명하려면 수신 설정과 실제 도착 결과가 필요하다. 이 실습에서는 그 외부 전달을 새로 시험하지 않았다. Grafana가 열리고 경보 목록이 비어 있다는 결과를 운영 알림 체계 전체의 검증으로 바꾸지 않은 이유다.

## 이번에 확인한 범위

이번 수동 실습에서는 Grafana 로그인과 대시보드, LND scrape 네 개, 규칙 리소스와 평가 상태를 확인했다. 여기까지는 관측 화면과 규칙이 동작한다는 증거다.

하지만 장애를 일부러 만들어 경보가 Firing으로 변하는지, Alertmanager를 거쳐 외부 수신자에게 도착하는지는 이번 과정에서 새로 검증하지 않았다. 현재 저장소의 Alertmanager values도 `local-only` receiver를 사용한다. 과거 별도 장애 실습 기록과 이번 화면 확인을 합쳐서 “방금 알림 전달까지 성공했다”고 쓰지 않았다.

Phase 1~5를 실습하며 가장 많이 바뀐 것은 완료의 기준이었다. Pod 실행, 지갑 동기화, 중계 성공, swap 성공, 지표 수집, 알림 전달은 각각 다른 결과다. 이후 kagent 진단을 붙이더라도 이 구분을 유지해야 한다. 모델이 설명을 잘하는 것보다, 어떤 근거가 있고 무엇이 아직 확인되지 않았는지 정확히 말하는 것이 먼저다.

관련 파일: [알림 규칙](../../charts/monitoring-rules.yaml), [관측 설정](../../charts/monitoring-values.yaml). 이것으로 Phase 1~5 회고를 마치고, 보안·백업·GitOps·kagent는 후속 실습으로 남긴다.
