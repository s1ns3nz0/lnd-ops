# Grafana가 이미 있었다: 기존 설치를 찾아 관측 연결하기

> Lightning 노드 운영 회고 7편 · Phase 5 전반 · 2026-09-28 Mac 수동 실습 기준

LND를 가게, Prometheus를 기록 담당자, Grafana를 현황판으로 생각해 보자. 가게가 현재 상태를 숫자로 알려주면 기록 담당자가 시간과 함께 보관하고, 현황판은 그 기록을 그림으로 보여준다. 이 글에서는 실제 코드로 그 연결을 따라간다.

## 누가 숫자를 만들고 저장하고 보여주나

LND가 자신의 상태를 HTTP 지표로 제공하더라도, 그 값을 시간에 따라 저장하고 화면에 보여주는 작업은 따로 필요하다. 이 lab의 관측 경로는 다음과 같다.

```text
LND RPC → lndmon·payment collector ─┐
LND 자체 metrics ──────────────────┤
Kubernetes·Node exporter ───────────┤
                                   ▼
                      Prometheus: 주기적 수집·저장·규칙 평가
                         ├─ Grafana: 조회·시각화
                         └─ Alertmanager: 경보 묶기·전달
```

Prometheus Operator는 Kubernetes의 선언을 읽어 Prometheus와 Alertmanager 구성을 관리한다. kube-state-metrics는 Pod Ready 같은 Kubernetes 객체의 상태를 지표로 제공하고, node-exporter는 운영체제의 CPU·메모리·파일시스템 지표를 제공한다. Grafana는 이 값을 만드는 프로그램이 아니라 Prometheus를 데이터 소스로 조회하는 화면이다.

어느 화면이 비었을 때 이 역할 구분이 도움이 됐다. Grafana 패널 문제, Prometheus의 수집 실패, exporter가 값을 만들지 못하는 상황은 고칠 위치가 다르다. Grafana를 재시작하는 것만으로 모든 경우를 해결할 수는 없다.

## 코드로 보는 숫자의 여행

가게인 LND, 기록 담당자인 Prometheus, 현황판인 Grafana가 실제로 어떻게 이어지는지 코드를 따라가 보자. 아래 코드는 저장소에서 필요한 부분만 발췌했다. 완전한 설치 YAML은 아니므로 조각만 따로 적용하는 예제가 아니다.

코드에서 자주 나오는 이름을 먼저 정리하자.

| 이름 | 이 글에서의 뜻 |
|---|---|
| Pod | LND와 보조 프로그램이 함께 실행되는 묶음 |
| sidecar | 같은 Pod에 둔 보조 컨테이너 |
| RPC | 프로그램끼리 상태나 작업을 요청하는 통신 |
| Service | 대상 Pod에 연결하는 내부 창구 |
| namespace | Kubernetes 리소스를 구분하는 구역 |
| endpoint | Prometheus가 실제 접속할 대상 주소·포트 |

### 1. LND가 숫자를 보여주는 창구를 연다

`charts/lnd-ops/templates/lnd.yaml`에는 다음 조건이 있다.

```gotemplate
{{- if $root.Values.monitoring.enabled }}
- --prometheus.enable
- --prometheus.listen=0.0.0.0:8989
{{- end }}
```

`monitoring.enabled`가 true이면 LND 실행 옵션에 두 줄을 넣는다. 첫 줄은 metrics 기능을 켜고, 두 번째 줄은 컨테이너에서 8989 포트로 듣게 한다. `0.0.0.0`은 브라우저에서 방문할 주소가 아니라 프로그램이 어느 인터페이스에서 연결을 받을지 정하는 값이다. 이것만으로 인터넷에 공개되지는 않는다.

### 2. lndmon이 옆에서 상태를 정리한다

같은 파일의 lndmon 실행 인자 중 두 줄이다.

```yaml
args:
  - --lnd.host=127.0.0.1:10009
  - --prometheus.listenaddr=0.0.0.0:9092
```

첫 줄은 “같은 Pod 안의 LND에게 RPC로 물어봐”라는 뜻이다. 두 번째 줄은 “정리한 지표를 9092 포트에서 보여줘”라는 뜻이다. 실제 template에는 인증서·macaroon·네트워크 설정도 함께 있다. 위 두 줄만으로 인증까지 준비되는 것은 아니다.

LND 자체의 8989와 lndmon의 9092는 서로 다른 창구다. 뒤의 예시는 lndmon 창구를 따라간다.

### 3. Service가 창구에 이름을 붙인다

같은 template의 Service 포트 선언이다.

```yaml
- {name: lndmon, port: 9092, targetPort: 9092}
```

`name`은 창구 이름, `port`는 Service 쪽 포트, `targetPort`는 연결할 Pod 쪽 포트다. 이 Service는 label로 LND Pod를 선택한다. 특히 `lndmon`이라는 이름은 다음 단계에서 Prometheus가 대상을 고를 때 사용한다.

### 4. Prometheus가 창구를 찾고 이름표를 붙인다

`charts/monitoring-values.yaml`의 lndmon job에서 발췌한 부분이다.

```yaml
job_name: lndmon
kubernetes_sd_configs:
  - role: endpoints
    namespaces:
      names: [lnd-regtest, lnd-testnet]
relabel_configs:
  - source_labels: [__meta_kubernetes_endpoint_port_name]
    action: keep
    regex: lndmon
  - source_labels: [__meta_kubernetes_namespace]
    target_label: namespace
  - source_labels: [__meta_kubernetes_service_name]
    target_label: service
```

`job_name`은 수집 작업의 이름이다. `kubernetes_sd_configs`는 두 namespace에서 endpoint를 찾으라는 설정이다. `relabel_configs`의 첫 규칙은 “발견한 포트 중 이름이 lndmon인 것만 남겨”라는 뜻이다. 이어지는 두 규칙은 Kubernetes에서 찾은 namespace와 Service 이름을 수집 데이터의 이름표로 옮긴다. 이것이 이 구성에서 속성을 붙이는 실제 코드다.

LND 프로그램에 값을 주입하는 작업이 아니라 Prometheus 수집 대상에 label을 붙이는 작업이다. Prometheus는 찾은 주소의 `/metrics`를 주기적으로 요청해 숫자를 가져온다.

예를 들어 `namespace="lnd-testnet"`, `service="lnd-0"`라는 이름표가 붙으면 같은 종류의 숫자도 어느 노드에서 왔는지 구별할 수 있다. 위 코드의 `names`에 적힌 두 namespace가 탐색 범위다. `__meta_` 이름은 발견 과정에서 쓰는 임시 정보이므로 최종 조회에 필요한 항목을 `target_label`로 옮긴다.

저장된 지표 모양은 다음처럼 읽을 수 있다. 실측 출력이 아니라 형식 예시다.

```text
lnd_chain_synced{job="lndmon",namespace="lnd-testnet",service="lnd-0"} 1
```

`lnd_chain_synced`와 값은 exporter가 만들고, 수집 설정은 출처 label을 붙인다. 같은 이름의 label이 이미 있으면 충돌 처리 설정도 영향을 준다. exporter의 원본 응답과 Prometheus의 최종 label이 같을 필요는 없다.

### 5. Grafana가 기록 담당자에게 질문한다

`charts/dashboards/lnd-ops-overview.json`의 첫 패널에서 필요한 필드만 추린 JSON이다.

```json
{
  "title": "lndmon scrape up",
  "type": "stat",
  "datasource": {"type": "prometheus", "uid": "prometheus"},
  "targets": [
    {"expr": "sum by (namespace, service) (up{job=\"lndmon\"})"}
  ]
}
```

`title`은 화면 제목, `type: stat`은 숫자를 보여주는 패널이다. `datasource`는 사용할 Prometheus 연결을 고르고, `expr`는 그 기록에서 무엇을 가져올지 묻는 질문이다.

조회식의 `{job="lndmon"}`은 lndmon 작업만 고르는 필터다. `sum by (namespace, service)`는 같은 namespace와 Service 이름표를 가진 값끼리 더하라는 뜻이다. 이런 질문을 쓰는 언어가 PromQL이다.

여기서는 lndmon 수집 성공 여부인 `up`을 namespace·Service별로 합산한다. 대상 하나라면 1은 수집 성공, 0은 수집 실패다. 대상이 여러 개면 성공한 대상 수가 될 수 있고, 대상 자체가 없으면 데이터가 없을 수 있다. 이것은 결제 성공 여부를 보여주는 패널이 아니다.

### 6. ConfigMap이 화면 설계도를 전달한다

`ops/deploy-monitoring`은 다음 label을 대시보드 ConfigMap에 붙인다. 아래는 실제 스크립트 발췌이며 지금 실행하라는 명령이 아니다.

```bash
kubectl -n "$namespace" label configmap lnd-ops-dashboards grafana_dashboard=1 --overwrite >/dev/null
```

이때 `$namespace`는 스크립트가 정한 관측 namespace를 담은 셸 변수다. LND에 전달하는 환경변수나 지표 label 자체가 아니다. 그 앞 단계에서 대시보드 JSON 파일들을 ConfigMap에 담는다. Grafana 옆의 dashboard sidecar는 설정된 범위에서 이 이름표를 가진 ConfigMap을 찾아 화면 설정으로 공급한다.

여기서 `grafana_dashboard=1`은 “대시보드 파일이 들어 있는 상자”라는 표시다. 앞에서 Prometheus 지표에 붙인 `namespace`·`service` label과 용도가 다르다. label은 마법의 명령이 아니라, 그 이름표를 읽도록 설정된 프로그램이 있을 때 의미를 갖는다.

```text
LND/lndmon이 숫자를 제공
  → Service·endpoint 정보로 수집 위치 발견
  → Prometheus가 숫자와 이름표를 기록
  → Grafana 패널의 조회식으로 기록을 읽어 표시
```

따라서 새 패널을 만들 때는 “이 숫자를 내보내는 곳이 있는가 → Prometheus가 수집하는가 → Grafana가 맞는 이름표로 조회하는가” 순서로 보면 된다. 이미 수집하는 숫자라면 LND를 수정하지 않고 패널 조회식만 바꿀 수 있다.

## 새로 설치하려던 이름은 이미 사용 중이었다

Helm이 멈춘 이유는 Grafana의 ClusterRole이었다. 소유권 annotation에는 기존 release namespace인 `lnd-monitoring`이 적혀 있었는데, 새 명령은 `lndops-monitoring`을 지정하고 있었다.

```text
ClusterRole "lnd-ops-monitoring-grafana-clusterrole" exists
meta.helm.sh/release-namespace:
expected lndops-monitoring, current lnd-monitoring
```

ClusterRole은 namespace마다 별도로 존재하는 리소스가 아니다. namespace만 바꾼다고 같은 이름의 리소스를 새로 만들 수 없었다. 이때 삭제하거나 annotation을 덮어쓰는 대신 기존 release를 조회했다.

```bash
helm list -A --filter '^lnd-ops-monitoring$'
kubectl -n lnd-monitoring get pods,pvc
```

실제 출력에는 `lnd-monitoring`의 `lnd-ops-monitoring` release가 revision 5, `deployed`로 나왔다. chart는 `kube-prometheus-stack-91.4.1`이었다.

Grafana, Prometheus, Alertmanager, Operator, kube-state-metrics, node-exporter Pod들이 Ready였고 Prometheus 10Gi PVC도 Bound였다.

따라서 이번 실습은 새 관측 환경의 완전한 설치가 아니라, 기존 배포를 발견하고 연결과 수집 상태를 확인한 과정으로 기록하는 것이 맞다. 먼저 만든 다른 namespace의 ConfigMap·Secret이 기존 Grafana에 사용됐다고 볼 수도 없다. 그 리소스들의 정리 완료는 이번 기록에서 확인하지 않았다.

## 설치 패키지와 화면 설계도는 따로 있다

관측 기반은 Prometheus Community의 kube-prometheus-stack 차트를 사용한다. 저장소에는 내려받은 차트를 `charts/vendor`에 보관하고, lab 설정은 `charts/monitoring-values.yaml`로 관리한다.

대시보드는 다른 부분이다. `charts/dashboards/*.json`은 이 프로젝트의 LND·결제·Kubernetes 운영 화면이고, JSON에는 패널 배치·제목·조회식이 들어 있다. 실제 지갑 잔액을 ConfigMap에 저장하는 것이 아니다.

```text
대시보드 JSON → ConfigMap → Grafana 화면 구성
LND와 exporter → Prometheus → Grafana가 조회할 실제 값
```

Helm 차트에도 기본 대시보드가 있을 수 있으므로 Grafana에 보이는 모든 화면이 우리 JSON에서 나온다고 단정하지 않았다. 화면 제목과 provisioning 설정을 구분해서 봐야 한다.

ConfigMap에는 JSON 파일의 내용을 key별 데이터로 담고 `grafana_dashboard=1` label을 붙인다. Grafana의 대시보드 sidecar가 선택 조건에 맞는 ConfigMap을 읽어 provisioning에 연결하는 구성이다. 그러므로 파일만 저장하거나 아무 namespace에 ConfigMap만 만들었다고 화면에 나타나는 것은 아니다.

실행 중인 sidecar의 선택 label과 namespace 범위도 맞아야 한다.

대시보드 JSON에서 중요한 항목은 `title`, 패널의 `gridPos`, `datasource`, `targets[].expr`, 표시 단위와 임계값이다. 예를 들어 다음은 현재 overview 대시보드에서 사용하는 송신 여력 조회식이다.

```promql
sum by (namespace, service) (
  lnd_channels_bandwidth_outgoing_sat{status="active"}
)
```

활성 채널들의 송신 여력을 namespace와 Service별로 합산한다. 그래프가 30,000 sat를 보여줘도 하나의 채널에서 30,000 sat를 보낼 수 있다는 의미는 아니다. 10,000 sat 채널 세 개를 합친 값일 수도 있다. 단일 채널 능력을 볼 때는 합계와 별도로 채널별 값이나 최댓값을 봐야 한다.

실제 values에는 Prometheus 보존 기간 14일과 10Gi PVC 요청이 들어 있다. 14일은 시간 기준 설정이고, 10Gi는 저장 공간 요청이다. 지표 개수와 수집 빈도에 상관없이 14일 분량이 무조건 들어간다는 보장은 아니다. Grafana 관리자 정보는 `lnd-ops-grafana-admin`이라는 기존 Secret을 참조하고, Grafana Service는 ClusterIP로 둔다.

`ops/deploy-monitoring`이 하는 일도 이 구성으로 풀어 볼 수 있다. 고정한 vendored 차트의 checksum 확인, namespace와 label 준비, 대시보드 ConfigMap 생성, 관리자 Secret이 없을 때 생성, Helm 적용, PrometheusRule 적용, 관측 준비 검사를 순서대로 수행한다.

다만 이 스크립트의 기본 namespace는 `lndops-monitoring`이며 이번 Mac의 기존 namespace `lnd-monitoring`과 다르다. 현재 Mac에서 그대로 실행해 기존 배포를 갱신했다고 주장하지 않는 이유다.

## 내 브라우저에서 내부 화면으로 통로 열기

기존 namespace를 사용해 Grafana와 Prometheus에 접속했다. 각각 별도 터미널에서 실행했다.

```bash
kubectl -n lnd-monitoring port-forward \
  svc/lnd-ops-monitoring-grafana 3000:80
```

```bash
kubectl -n lnd-monitoring port-forward \
  svc/lnd-ops-monitoring-kube-pr-prometheus 9090:9090
```

명령을 유지한 채 브라우저에서 Grafana는 `http://localhost:3000`, Prometheus는 `http://localhost:9090`을 연다. `3000:80`의 왼쪽은 내 컴퓨터 포트, 오른쪽은 Service 포트다. 두 명령은 각각 별도 터미널에서 유지한다.

Grafana에는 기존 배포가 참조하는 Secret으로 로그인했다. 새 namespace에 만든 Secret을 가져다 기존 비밀번호라고 생각하면 안 됐다. Secret 값은 글에 포함하지 않는다.

Prometheus 화면이 안 열린 적도 있었다. port-forward를 다시 시작하니 접속됐다. 이 경로의 종료는 로컬 브라우저 접속에 영향을 주지만, 클러스터 안의 수집 프로세스를 종료시키지는 않는다.

## 내 브라우저가 못 가도 Prometheus는 갈 수 있다

Targets 화면의 내부 Pod 주소를 클릭했을 때 Mac 브라우저에서는 열리지 않았다. 대신 Prometheus 쿼리 화면에서 다음을 실행했다.

```promql
up{namespace="lnd-testnet"}
```

그 결과 `lndmon`, `lnd-payments`, `lnd-grpc`, `lnd-wallet-state` 네 series의 값이 모두 1이었다. 실제 화면으로 이 네 대상의 scrape 성공을 확인한 것이다. 내부 주소에 대한 호스트 브라우저의 접근과 Prometheus의 접근은 같은 네트워크 경로가 아니었다.

`up=1`은 해당 대상의 scrape 성공을 나타낸다. 정의는 [Prometheus jobs and instances 문서](https://prometheus.io/docs/concepts/jobs_instances/)에서 확인했다. 모든 업무 지표의 정확성까지 보장하지는 않지만, “metrics 링크가 안 열리니 수집이 안 된다”는 추측을 고치는 데는 충분한 근거였다.

이후 Grafana에서도 LND 관련 대시보드 값이 표시되는 것을 확인했다.

## 수집 대상 네 개의 정체

이 lab은 LND 대상에 대해 `additionalScrapeConfigs`로 Kubernetes endpoint 탐색을 설정한다. `lnd-regtest`와 `lnd-testnet` namespace를 보고, Service port 이름을 기준으로 대상을 고른 뒤 namespace와 Service 이름을 지표 label에 붙인다. 별도의 ServiceMonitor가 있어야만 수집되는 구성으로 이해하면 이 설정을 놓친다.

endpoint 탐색과 relabel 동작은 [Prometheus 설정 문서](https://prometheus.io/docs/prometheus/latest/configuration/configuration/)와 대조했다.

| Prometheus job | 선택하는 Service port 이름 | HTTP 경로·포트 | 확인할 대상 |
|---|---|---|---|
| `lndmon` | `lndmon` | `/metrics`, 9092 | LND 상태 exporter |
| `lnd-grpc` | `lnd-metrics` | `/metrics`, 8989 | LND 자체 지표 |
| `lnd-payments` | `payment-metrics` | `/metrics`, 9093 | 결제·지갑 등 collector |
| `lnd-wallet-state` | `payment-metrics` | `/wallet-state`, 9093 | 지갑 잠금·RPC 상태 |

네 job이 반드시 Pod 네 개라는 뜻은 아니다. 마지막 두 job은 같은 collector 포트의 서로 다른 HTTP 경로를 조회한다. 이 매핑을 알고 나면 `up`의 `job`, `instance`, `namespace`, `service` label을 보고 어느 경로를 확인한 것인지 구분할 수 있다.

관측 values에는 Loop health job도 정의돼 있다. 다만 대상 endpoint가 있어야 series가 생긴다. 당시 화면에서 확인한 네 개와 현재 소스에 정의된 가능한 job 목록을 같은 수로 취급하지 않았다.

## 이미 있는 LND에 무엇을 추가하나

여기서 “기존 배포에 속성을 넣는다”는 말은 세 가지 작업으로 나눠야 한다. 프로그램이 지표를 내보내도록 설정하는 것, Prometheus가 그 주소를 발견하고 label을 붙이는 것, Grafana가 저장된 지표를 조회하도록 화면을 설정하는 것이다. Grafana를 설치한다고 LND에 자동으로 계측 코드가 들어가는 구조는 아니다.

이 lab에서 LND는 Deployment가 아니라 StatefulSet이다. 현재 chart는 관측 활성화 시 기존 `lnd-0` StatefulSet과 관련 리소스에 다음 항목을 구성한다. 실제 실행 중인 release의 활성화 여부와 override는 별도 조회 대상이다.

| 위치 | 관측 활성화 시 추가되는 내용 | 역할 |
|---|---|---|
| `lnd` 컨테이너 인자 | `--prometheus.enable`, `--prometheus.listen=0.0.0.0:8989` | LND 자체 metrics 제공 |
| 같은 Pod의 `lndmon` 컨테이너 | LND RPC를 `127.0.0.1:10009`로 조회 | 채널·체인 등의 상태를 metrics로 변환 |
| 같은 Pod의 `payment-metrics` 컨테이너 · 이미지 설정 시 | collector 코드와 인증 경로 설정 | 결제·지갑·백업 상태를 metrics로 제공 |
| `lnd-0` Service | 이름이 붙은 metrics 포트 | Prometheus가 수집할 endpoint 발견에 사용 |
| NetworkPolicy | 관측 namespace에서 metrics 포트 접근 허용 | 실제 수집 통신 허용 |

`lndmon`과 `payment-metrics`는 sidecar, 즉 LND와 같은 Pod에 배치되는 보조 컨테이너다. 같은 Pod의 네트워크를 공유하므로 localhost로 LND에 접근할 수 있다. 별도의 VM이나 LND 지갑을 하나 더 만드는 방식은 아니다. 현재 chart에서는 collector 이미지가 설정돼 있을 때 `payment-metrics`를 추가한다.

지갑과 채널 상태는 기존 LND PVC에 그대로 둔다. 보조 컨테이너는 인증서와 읽기 권한 macaroon 등을 읽기 전용 마운트로 참조한다. 다만 Pod template 변경은 Pod 교체를 일으킬 수 있다. 그래서 기존 지갑 보존과 별개로 변경 뒤 unlock, 동기화, 채널 활성 상태를 확인해야 했다.

## 설정 파일과 파일 위치를 프로그램에 전달하기

이 lab의 collector는 `charts/lnd-ops/files/payment_metrics.py`를 ConfigMap에 담고, 컨테이너의 `/app/payment_metrics.py`에 파일로 마운트한다. 실행 명령은 `python3 /app/payment_metrics.py`다. 이미지에 코드가 자동으로 합쳐지는 것이 아니라, Pod 실행 시 파일 경로가 연결되는 것이다.

인증서와 데이터 위치는 컨테이너 환경변수로 전달한다. 현재 template에서 사용하는 값 중 일부를 발췌하면 다음과 같다.

```yaml
env:
  - name: LND_TLS_CERT
    value: /data/.lnd/tls.cert
  - name: LND_READONLY_MACAROON
    value: /data/.lnd/data/chain/bitcoin/testnet/readonly.macaroon
  - name: LND_BACKUP_STATUS
    value: /backup-status/lnd-0.status
```

위 예시는 testnet 첫 노드 기준으로 template 값을 풀어 쓴 것이다. 경로를 환경변수에 넣었다고 해당 파일이 생기는 것은 아니다. PVC·ConfigMap volume과 volumeMount가 그 경로를 제공해야 하고, 프로그램도 해당 변수 이름을 읽도록 구현돼 있어야 한다.

Pod에 임의의 환경변수를 추가하거나 label을 붙이는 것만으로 새 metric이 생기지는 않는다. 예를 들어 새로운 업무 처리 건수를 보고 싶다면 프로그램 또는 exporter가 그 건수를 계산해 metrics 응답에 노출해야 한다. Kubernetes의 CPU·메모리 지표만으로 결제 성공 건수를 알아낼 수 없는 이유다.

collector 코드는 `subPath`로 마운트한다. 이 방식의 파일은 ConfigMap을 수정해도 실행 중인 컨테이너에 자동 갱신되는 것으로 기대하면 안 된다. 현재 Pod가 사용하는 코드가 바뀌었는지는 rollout과 마운트 방식을 함께 확인해야 한다. [Kubernetes ConfigMap 동작](https://kubernetes.io/docs/concepts/configuration/configmap/)

## 숫자에 Mac·WSL 이름표를 붙이려면

현재 job은 `namespace`와 `service`를 붙이지만, 그것만으로 두 클러스터를 구분할 수는 없다. Mac과 WSL 양쪽에 `lnd-testnet/lnd-0`이라는 이름이 존재하기 때문이다. 각 Grafana가 자기 클러스터의 Prometheus만 조회한다면 데이터 소스가 관측 범위를 나눈다. 두 환경을 함께 비교하려면 데이터 소스와 label 설계를 명시적으로 맞춰야 한다.

예를 들어 해당 클러스터의 기존 job `relabel_configs`에 다음 항목을 추가하면 그 job이 수집하는 시계열에 정적인 `cluster` label을 붙일 수 있다. 이는 **설명용 변경 예시이며 현재 배포에 적용한 설정이 아니다.**

```yaml
- target_label: cluster
  replacement: mac-lab
```

WSL 쪽에서는 다른 값인 `wsl-lab`을 사용한다. 관련 job에 일관되게 설정해야 같은 조건으로 비교할 수 있다. `external_labels`는 외부 시스템으로 전달할 때 사용하는 별도 설정이므로, 그것만 추가하면 로컬 PromQL 결과에도 같은 label이 자동으로 붙는다고 혼동하지 않는다.

[Prometheus label·relabel 설정](https://prometheus.io/docs/prometheus/latest/configuration/configuration/)

동적인 애플리케이션 속성이라면 먼저 Kubernetes metadata 또는 exporter 출력 중 어디에 둘지 정한다. Service의 label을 읽으려면 탐색 결과에서 해당 메타데이터를 target label로 옮기는 규칙이 필요하다. Deployment 최상위 `metadata.labels`와 Pod의 `spec.template.metadata.labels`도 다른 위치다.

최상위 label이 자동으로 Pod·Service·metrics 모두에 복사되는 것은 아니다.

지표 label은 환경·서비스처럼 값의 종류가 제한된 속성에 사용한다. 결제 hash나 요청마다 다른 식별자를 붙이면 값 조합마다 시계열이 늘어난다. 이 lab의 collector가 개별 결제 비밀값 대신 시간 창의 건수와 합계를 내보내는 이유도 운영 화면에 필요한 정보 범위를 제한하기 위해서다.

## Grafana에게 기록 위치와 조회 방법 알려주기

Grafana에는 우선 Prometheus 데이터 소스가 있어야 한다. 데이터 소스는 Prometheus API 주소와 필요한 접속 설정을 담고, 대시보드 패널은 그 데이터 소스의 UID와 PromQL을 참조한다. 이 lab의 대시보드 JSON은 `prometheus` UID를 사용한다. 같은 이름의 데이터 소스를 만들어도 UID가 다르면 기존 패널의 참조와 맞지 않을 수 있다.

vendored kube-prometheus-stack의 기본값에는 Prometheus 데이터 소스 생성과 UID `prometheus`가 설정돼 있다. 대시보드 sidecar도 기본적으로 `grafana_dashboard=1`을 찾으며 namespace 탐색 범위는 `ALL`이다. 따라서 다른 namespace에 만든 ConfigMap도 선택될 가능성이 있다.

실제 기존 release가 이 기본값을 유지했는지는 저장된 values와 실행 설정으로 확인해야 한다. 이번 Mac 실습에서 새 ConfigMap이 사용됐다고 단정하지 않은 이유다.

```text
브라우저에서 패널 열기
  → Grafana가 데이터 소스·PromQL·조회 시간 범위를 사용
  → Prometheus API가 저장된 시계열을 조회
  → Grafana가 결과를 그래프·표·상태 패널로 표시
```

대시보드 refresh 간격은 화면을 다시 조회하는 주기이고, Prometheus scrape interval은 원본 데이터를 수집하는 주기다. 화면을 1초마다 새로 고쳐도 수집 주기가 더 길면 새로운 원본 샘플이 매번 생기지는 않는다. Grafana 패널 threshold를 바꾸는 것 역시 표시 색상을 바꾸는 작업이며, 현재 lab의 PrometheusRule 경보 기준을 자동으로 변경하지 않는다.

기존 배포를 사용한다면 새 Grafana를 설치하기보다 현재 데이터 소스 UID·주소와 대시보드 공급 경로부터 확인한다. 파일로 관리되는 데이터 소스와 대시보드는 그 provisioning 설정에 맞춰 갱신해야 한다. [Grafana provisioning 문서](https://grafana.com/docs/grafana/latest/administration/provisioning/)

## 이미 설치된 환경에서 어느 파일을 고치나

| 바꾸려는 내용 | 현재 저장소의 수정 위치 | 변경 뒤 확인할 것 |
|---|---|---|
| LND metrics·sidecar 켜기 | `charts/lnd-ops/values.yaml`의 기능값과 `templates/lnd.yaml` | 기존 플래그 보존, Pod·지갑·채널 상태 |
| collector가 계산하는 값 | `charts/lnd-ops/files/payment_metrics.py` | ConfigMap 반영과 실행 코드, metrics 응답 |
| 수집 대상·주기·target label | `charts/monitoring-values.yaml`의 scrape job | Prometheus 활성 설정·Targets·실제 label |
| 패널 조회식·제목·단위 | `charts/dashboards/*.json` | ConfigMap 선택과 데이터 소스 UID, 패널 결과 |
| 경고 기준 | `charts/monitoring-rules.yaml` | Prometheus Rules 평가 상태 |

이 표는 기존 배포의 설정 경로를 설명한다. 현재 Mac의 release namespace는 `lnd-monitoring`인데 설치 스크립트 기본값은 `lndops-monitoring`이므로, 변경 적용 전에 소유 release·namespace·override를 확인해야 한다. Helm이나 GitOps가 관리하는 리소스를 즉석 수정하면 다음 반영에서 덮일 수 있으므로 관리 원본에 변경을 남기는 것이 필요하다.

여기서는 문서 설명만 추가했으며 실제 리소스를 수정하지 않았다.

```bash
helm list -A --filter '^lnd-ops-monitoring$'
helm get values lnd-ops -n lnd-testnet --all
helm get values lnd-ops-monitoring -n lnd-monitoring --all
kubectl -n lnd-testnet get statefulset lnd-0 -o yaml
kubectl get configmaps -A -l grafana_dashboard=1
```

위 명령은 실습에서 사용한 이름 기준이다. values·YAML 출력 전체를 공개하기보다 설정 항목만 확인한다. 그다음 Prometheus Targets에서 수집 여부를 보고, 조회 결과에 원하는 label이 실제로 붙었는지 확인한 뒤 Grafana 패널을 확인하면 변경이 어느 단계에서 반영되지 않았는지 좁힐 수 있다.

## 화면이 비었을 때 어디부터 확인하나

먼저 Prometheus Targets에서 대상이 아예 없는지, 있는데 Down인지 나눈다. 대상이 없다면 namespace 탐색 범위, Service port 이름과 endpoint부터 본다. 대상이 있고 Down이면 표시된 scrape 오류를 읽고 포트·프로세스·네트워크 경로를 확인한다. `up=1`인데 원하는 metric만 없다면 exporter의 수집 항목과 인증, metric 이름·label을 살핀다.

NetworkPolicy의 관측 허용 조건은 namespace 문자열 그 자체가 아니라 `lnd-ops-monitoring: "true"` label이다. 실제 관측 namespace에 그 label이 있는지와 목적 포트가 허용되는지를 함께 확인한다. Service selector는 Pod 선택, scrape relabel 설정은 수집 대상 선택, NetworkPolicy는 통신 허용이라는 서로 다른 역할이다.

```bash
kubectl get namespace lnd-monitoring --show-labels
kubectl -n lnd-testnet get service lnd-0 -o yaml
kubectl -n lnd-testnet get endpointslices \
  -l kubernetes.io/service-name=lnd-0 -o wide
kubectl -n lnd-testnet get networkpolicy
```

마지막으로 Grafana에서만 No data라면 데이터 소스, 패널의 PromQL, 시간 범위와 변수 선택을 본다. Prometheus에 직접 같은 조회식을 넣어 값이 나오는지 확인하면 수집 문제와 화면 문제를 분리할 수 있다. 이 순서로 확인해야 브라우저 링크 하나가 안 열린다는 이유로 노드 전체를 다시 배포하지 않게 된다.

이번 실습의 결과는 기존 관측 스택의 사용 가능성과 네 가지 LND 수집 대상 확인이다. 그다음에는 수집된 숫자를 어떤 조건에서 경고로 바꿀지 살펴봤다.

관련 파일: [관측 values](../../charts/monitoring-values.yaml), [대시보드 JSON](../../charts/dashboards), [설치 스크립트](../../ops/deploy-monitoring). 재현할 때는 이 글의 namespace를 그대로 쓰기 전에 `helm list -A`로 자신의 release를 확인해야 한다.
