# Helm으로 LND 설정하기: Chart에서 StatefulSet까지

> Lightning 노드 운영 회고 2편 · Phase 1~2 · 2026-09-29 저장소 소스 기준

Helm은 설치 설명서를 읽고 Kubernetes에 필요한 리소스를 만들어 주는 도구다. 처음에는 이 설명서까지 LND에서 공식으로 제공한 것으로 생각했다. 실제로 이 lab에서 사용한 `charts/lnd-ops`는 프로젝트에서 직접 작성한 차트였다. LND 실행 이미지를 사용하는 것과 Kubernetes 배포 구성을 직접 만드는 것은 서로 다른 작업이었다.

이 글에서는 차트 파일을 따라가며 어떤 설정이 어떤 리소스와 LND 실행 옵션으로 바뀌는지 살펴본다. 실행 중인 클러스터의 최신 상태가 아니라, 작성 시점의 소스와 로컬 렌더링 결과를 기준으로 설명한다.

[앞 글](01-kubernetes-and-regtest.md)에서 다룬 핵심은 Pod 교체 뒤에도 같은 볼륨과 지갑을 이어 쓰는 것이었다. 여기서는 그 구조를 Helm이 어떻게 생성하는지 본다.

## 설치 설명서·선택값·완성된 설치를 구분하기

Chart는 설치 설명서 묶음이다. `values.yaml`은 선택값을 적는 곳이고, `templates/`는 그 값을 채울 틀이다. 이 둘로 실제 설치한 한 묶음을 release라고 부른다. 우리 release 이름은 `lnd-ops`다.

```text
Chart.yaml                       차트 이름·버전
values.yaml                      기본 설정
values-testnet.yaml              testnet용 덮어쓰기
           ↓
templates/*.yaml + 합쳐진 values  Helm 렌더링
           ↓
Service / StatefulSet / NetworkPolicy 등의 YAML
           ↓ 설치·업데이트를 실행했을 때
Kubernetes가 Pod·PVC 등의 실제 리소스를 관리
```

Helm의 `.Values`는 합쳐진 설정, `.Release`는 release 이름과 namespace 같은 정보를 제공한다. 이 차트는 리소스 이름 대부분을 `lnd-0`처럼 고정하므로, release 이름만 바꾼다고 같은 namespace에 독립 노드 세트가 생기지는 않는다. [Helm 내장 객체 문서](https://helm.sh/docs/chart_template_guide/builtin_objects/)

짧은 예로 연결해 보자. 실제 testnet values에는 아래 값이 있다.

```yaml
lnd:
  storage: 30Gi
```

실제 template은 그 값을 이렇게 읽는다.

```gotemplate
storage: {{ $root.Values.lnd.storage }}
```

Helm이 빈칸을 채우면 다음 YAML이 된다.

```yaml
storage: 30Gi
```

`{{ ... }}`는 Kubernetes가 읽을 설정이 아니라 Helm이 먼저 계산할 부분이다. Kubernetes에는 계산이 끝난 `storage: 30Gi`가 전달된다. 파일에 30Gi를 적는 것, YAML을 만드는 것, 실제 저장 공간을 배정받는 것은 각각 다른 단계다.

선택 기능 이름도 먼저 풀어 보자. `lndmon`은 LND 상태를 숫자로 정리하는 도구다. `collector`는 정보를 모으는 프로그램, `sidecar`는 주 프로그램과 같은 Pod에 둔 보조 컨테이너를 뜻한다. `Loop`는 채널 쪽 자금과 온체인 자금을 교환하는 도구다.

## 파일마다 맡은 일

| 파일 | 이 lab에서 맡은 역할 |
|---|---|
| `Chart.yaml` | 이름 `lnd-ops`, 차트 버전 `0.2.0`, 앱 버전 표기 `0.21.3-beta` |
| `values.yaml` | regtest 기본값, 이미지, 자원, 저장 공간, 선택 기능 |
| `values-regtest.yaml`, `values-testnet.yaml` | 환경별 설정 덮어쓰기 |
| `templates/lnd.yaml` | LND Service·StatefulSet, 선택적 P2P NodePort·관측 sidecar |
| `templates/bitcoin.yaml` | regtest Bitcoin Core Service·StatefulSet |
| `templates/serviceaccount.yaml` | 노드용 ServiceAccount |
| `templates/networkpolicy.yaml` | profile·기능별 통신 정책 |
| `templates/loop.yaml` | 선택적 Loop Deployment·Service·PVC·ServiceAccount·ConfigMap |
| `templates/payment-collector-configmap.yaml` | 관측 collector의 Python 코드 전달 |
| `templates/backup-status-configmap.yaml` | collector가 읽는 백업 상태 전달 |

`appVersion`은 앱 버전 표기다. 실제 컨테이너 이미지는 `lnd.image`를 template이 읽어서 결정한다. 이 저장소는 이미지 digest를 지정하므로, `appVersion`만 수정한다고 실행 이미지가 바뀌지 않는다. 근거: [Chart.yaml](../../charts/lnd-ops/Chart.yaml), [기본 values](../../charts/lnd-ops/values.yaml).

## 기본 설정에서 testnet에 필요한 값만 바꾸기

testnet 파일은 의외로 짧다. 다음이 실제 전체 내용이다.

```yaml
profile: testnet
lnd:
  nodes: 1
  storage: 30Gi
```

나머지 값은 기본 `values.yaml`에서 가져온다. 이처럼 `-f`로 넘긴 파일이 기본값을 덮고, 같은 키를 `--set`으로 지정하면 그 값이 우선한다. [Helm values 문서](https://helm.sh/docs/chart_template_guide/values_files/)

| 설정 | 기본값 | testnet 파일 적용 뒤 의미 |
|---|---|---|
| `profile` | `regtest` | `testnet`, LND backend와 네트워크 정책 분기 |
| `lnd.nodes` | `2` | `1`, LND StatefulSet 한 개 생성 |
| `lnd.storage` | `10Gi` | `30Gi`, 각 LND의 PVC 요청 용량 |
| `lnd.resources.requests` | CPU `100m`, 메모리 `256Mi` | 그대로 상속 |
| `lnd.resources.limits` | CPU `2`, 메모리 `2Gi` | 그대로 상속 |
| `bitcoin.enabled` | `true` | 값은 남지만 testnet 조건에서는 Bitcoin Core 미생성 |
| `router.enabled` | `false` | 공개 P2P NodePort 비활성 |
| `monitoring.enabled` | `false` | 관측 sidecar 비활성 |
| `loop.enabled` | `false` | Loop 리소스 비활성 |

`bitcoin.enabled: true`만 보고 testnet에도 Bitcoin Core가 설치된다고 판단하면 틀린다. template은 `profile == regtest` 조건도 함께 검사한다. values는 입력이고, 실제 동작은 그 값을 사용하는 template까지 읽어야 알 수 있다.

30Gi는 이 lab의 요청값이다. 기존 PVC를 늘리거나 줄일 수 있다는 보장은 아니며, 운영 중 저장 공간 변경은 별도로 확인해야 한다.

CPU `100m`은 0.1 CPU에 해당하는 요청량이고, 메모리 `256Mi`는 스케줄링에 사용하는 요청량이다. limits는 각각 CPU 2, 메모리 2Gi다. 요청량과 사용량은 같지 않으며, 이 숫자들이 동기화 시간을 보장하는 것도 아니다. 차트가 LND를 실행할 자리를 얼마나 요구하고 사용 상한을 어떻게 설정했는지 읽는 값이다.

[Kubernetes 자원 관리 문서](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)

설정을 바꿀 때는 template을 먼저 수정할 필요가 없는 경우가 많다. 예를 들어 관측 기능은 이미 values에 노출돼 있으므로 override로 켤 수 있다. 반면 원하는 LND 인자가 template에 하드코딩돼 있고 values에서 읽지 않는다면, values에 임의의 키만 추가해도 효과가 없다. `values에 키 추가 → template에서 그 키 사용 → 렌더링에서 실제 인자 확인`까지 연결돼야 한다.

## 같은 입력에서 실제로 나오는 리소스

로컬 렌더링 결과를 리소스 종류별로 비교하면 차트의 범위가 드러난다.

| 종류 | 기본 regtest | 기본 testnet |
|---|---|---|
| LND StatefulSet | `lnd-0`, `lnd-1` | `lnd-0` |
| Bitcoin StatefulSet | `bitcoin` | 없음 |
| Service | `bitcoin`, `lnd-0`, `lnd-1` | `lnd-0` |
| ServiceAccount | `bitcoin-node`, `lnd-node` | `lnd-node` |
| NetworkPolicy | 5개 | 4개 |
| 저장 공간 요청 | 각 StatefulSet의 `volumeClaimTemplates` | LND의 `volumeClaimTemplates` |

Namespace는 이 목록에 없다. 이 저장소의 `ops/deploy`가 namespace를 만들고 label을 붙인 뒤 Helm을 호출하기 때문이다. `helm template --namespace lnd-testnet`의 namespace 인자는 렌더링 문맥을 정하며, 그것만 실행해서 실제 namespace가 생성되지는 않는다.

기본 상태에는 Loop나 collector ConfigMap도 없다. template 파일이 디렉터리에 존재한다는 사실과 해당 조건에서 리소스가 출력된다는 사실은 다르다.

## 빈칸이 있는 YAML을 실제 값으로 채우기

`lnd.yaml`은 다음 반복문으로 시작한다.

```gotemplate
{{- $root := . -}}
{{- range $i := until (int .Values.lnd.nodes) }}
```

`until 2`는 0과 1을 순회한다. 각 순회에서 `lnd-0`, `lnd-1`이라는 Service와 StatefulSet을 만든다. 각 StatefulSet의 `replicas`는 1이다. **`lnd.nodes: 2`는 하나의 지갑을 복제하는 설정이 아니라, 별도 저장 공간을 갖는 노드 두 개를 만드는 설정**이다.

반복문 안에서는 현재 문맥 `.`이 바뀌므로, 처음 저장한 `$root`로 전체 values에 접근한다. 예를 들어 아래 부분은 `lnd.storage` 값을 PVC 요청 용량에 넣는다.

```gotemplate
volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: [ReadWriteOnce]
      resources:
        requests:
          storage: {{ $root.Values.lnd.storage }}
```

testnet에서는 `storage: 30Gi`로 렌더링된다. Helm이 직접 출력하는 것은 StatefulSet 안의 PVC 템플릿이며, 이로부터 Kubernetes가 `data-lnd-0-0` PVC를 만든다. Pod 이름은 `lnd-0-0`, 컨테이너의 마운트 위치는 `/data`, LND 데이터 위치는 `/data/.lnd`다.

다른 곳에서는 `toYaml ... | nindent 12`로 resources 객체를 YAML로 바꾸고 들여쓰기를 맞춘다. `quote`는 문자열을 따옴표로 감싼다. `required`는 필수값이 없을 때 렌더링을 실패시킨다. 실제로 router를 켜면서 `router.externalIP`를 생략하면 오류가 난다. 근거: [LND template](../../charts/lnd-ops/templates/lnd.yaml).

## 완성된 설정은 LND 실행 옵션으로 들어간다

이 차트는 기본 LND 설정을 ConfigMap의 `lnd.conf`로 만드는 대신, StatefulSet의 컨테이너 `args`에 넣는다. testnet 분기에서 생성되는 핵심 인자는 다음과 같다.

```yaml
args:
  - --lnddir=/data/.lnd
  - --bitcoin.testnet
  - --bitcoin.node=neutrino
  - --rpclisten=0.0.0.0:10009
  - --restlisten=0.0.0.0:8080
  - --listen=0.0.0.0:9735
```

설명용 발췌라 TLS 관련 인자 등은 생략했다. regtest에서는 `--bitcoin.regtest`, `--bitcoin.node=bitcoind`와 Bitcoin Core RPC·ZMQ 주소를 사용한다. profile 하나가 단순 이름표가 아니라 실행 방식을 바꾸는 셈이다.

컨테이너가 포트를 듣는 것과 Service가 그 포트를 노출하는 것도 다르다. 기본 LND Service는 RPC 10009와 P2P 9735를 제공한다. REST 8080은 LND가 듣지만 이 Service의 포트 목록에는 없다.

`router.enabled`를 켜면 testnet의 첫 노드에 P2P NodePort Service를 추가하고 외부 주소를 LND 인자로 전달한다. 공유기나 호스트의 포트 전달까지 Helm이 자동 구성하는 것은 아니다.

LND StatefulSet은 `lnd-node` ServiceAccount를 사용하지만 `automountServiceAccountToken: false`로 API 토큰 자동 마운트를 끈다. LND가 채널과 결제를 처리하는 데 Kubernetes API를 조작할 필요가 없기 때문이다. macaroon은 LND에서 허용할 작업이 담긴 권한 증명이다. 이 설정과 LND의 macaroon은 서로 다른 인증 체계다.

전자는 Kubernetes API 접근, 후자는 LND RPC 접근에 관계한다.

### 보안 옵션은 이런 일을 한다

기본 실행 보안 설정에는 `allowPrivilegeEscalation: false`, Linux capabilities 전체 제거, `RuntimeDefault` seccomp이 있다. 각각 실행 중 권한 확대를 막고, 추가 Linux 권한을 제거하고, 시스템 호출에 기본 제한을 적용하는 설정이다. 이 항목들이 곧 LND를 관리자 계정이 아닌 non-root로 실행한다는 뜻은 아니다.

현재 LND template에는 사용자 ID를 강제하는 `runAsUser` 설정이 없으므로, 코드에 없는 보안 조건까지 충족했다고 쓰지 않았다.

TLS 관련 인자도 배포 구조와 연결된다. Loop는 LND를 Service 이름 `lnd-0`으로 호출하므로 LND 인증서에서 그 DNS 이름을 검증할 수 있어야 한다. 차트의 `--tlsextradomain=lnd-0`과 `--tlsautorefresh`는 이 연결을 지원하는 설정이다. 인증서를 가진 것과 해당 RPC 작업을 허용하는 macaroon을 가진 것은 별도 조건이다.

## 기능을 켜면 무엇이 추가되는가

기본 testnet 렌더링에서는 ServiceAccount 한 개, Service 한 개, StatefulSet 한 개, NetworkPolicy 네 개가 나왔다. 독립 PVC YAML은 없지만 StatefulSet의 `volumeClaimTemplates`가 저장 공간 생성을 요청한다.

`monitoring.enabled: true`는 같은 Pod에 `lndmon`을 추가하고 LND Prometheus 포트를 켠다. collector 이미지가 지정되어 있으면 `payment-metrics` 컨테이너와 관련 ConfigMap도 추가한다. **Prometheus·Grafana 전체 설치는 별도 관측 차트의 역할**이다.

`loop.enabled: true`는 별도의 Loop 리소스를 추가한다. 사용할 Loop 이미지와 인증 Secret 등이 준비돼 있어야 하며, 이 옵션만으로 swap 성공까지 보장하지 않는다. 지갑 생성·잠금 해제, 동기화, 채널 개설 역시 Helm 배포 성공과 별도로 확인한다.

## 적용하기 전에 완성된 YAML을 미리 보기

다음 명령은 저장소 루트에서 실행한다. `helm template`은 YAML을 로컬에서 출력하며 클러스터에 설치하지 않는다.

```bash
helm lint charts/lnd-ops -f charts/lnd-ops/values-testnet.yaml

helm template lnd-ops charts/lnd-ops \
  --namespace lnd-testnet \
  -f charts/lnd-ops/values-testnet.yaml \
  --show-only templates/lnd.yaml
```

관측 설정의 차이는 같은 명령에 `--set monitoring.enabled=true`를 추가해 비교할 수 있다. 렌더링은 문법과 생성 결과를 확인하는 단계다. 클러스터의 admission 정책, 이미지 실행, 실제 지갑 상태까지 검증하지 않는다. 백업 상태 template의 `lookup`처럼 클러스터의 기존 리소스를 참고하는 부분도 일반 로컬 렌더링에서는 실제 배포와 결과가 다를 수 있다.

관측 전후를 따로 파일에 렌더링해 보면 변경 지점을 읽기 쉽다. 아래 명령은 `/tmp`에 비교용 파일만 만든다.

```bash
helm template lnd-ops charts/lnd-ops -n lnd-testnet \
  -f charts/lnd-ops/values-testnet.yaml \
  --show-only templates/lnd.yaml > /tmp/lnd-base.yaml
helm template lnd-ops charts/lnd-ops -n lnd-testnet \
  -f charts/lnd-ops/values-testnet.yaml \
  --set monitoring.enabled=true \
  --show-only templates/lnd.yaml > /tmp/lnd-monitoring.yaml
diff -u /tmp/lnd-base.yaml /tmp/lnd-monitoring.yaml
```

차이가 있으면 `diff`는 종료 코드 1을 반환한다. 이 비교에서는 예상된 동작이다. 추가된 metrics 포트와 `lndmon`, collector 이미지가 설정돼 있다면 `payment-metrics` 컨테이너와 읽기 전용 마운트를 찾아보면 된다. 현재 기본 values에는 collector 이미지가 지정돼 있다.

LND 컨테이너의 Pod template이 바뀌는 작업이므로 실제 upgrade에서는 Pod 교체와 지갑 unlock이 필요할 수 있다.

이미 설치된 환경은 원하는 Mac 또는 WSL 클러스터의 kubeconfig를 선택한 뒤 다음처럼 비교한다.

```bash
kubectl config current-context
helm list -n lnd-testnet
helm get values lnd-ops -n lnd-testnet
helm get values lnd-ops -n lnd-testnet --all
helm get manifest lnd-ops -n lnd-testnet
kubectl -n lnd-testnet get statefulset lnd-0 -o yaml
```

차례대로 접속 대상, release, 사용자 입력값, 기본값을 포함한 계산 결과, release에 저장된 manifest, 현재 Kubernetes 리소스를 확인한다. release 이름이 다르면 목록에 나온 이름을 사용한다. values와 manifest 전체는 인증 정보 등이 포함될 수 있으므로 게시용 캡처와 구분한다.

실제 배포 스크립트인 [ops/deploy](../../ops/deploy)는 `helm upgrade --install`에 profile 파일과 기능별 `--set` 값을 전달한다. 따라서 현재 배포를 재현하려면 testnet 파일만 읽을 것이 아니라 추가 override도 확인해야 한다.

운영 중 기본 설정만 다시 적용하면 기존 관측·Loop·router 옵션을 빠뜨릴 수 있어, 여기서는 재설치 명령 대신 조회와 렌더링부터 확인했다.

이제 Helm 설치가 끝났다는 말은 필요한 Kubernetes 리소스를 전달했다는 의미로 읽힌다. 그 안에서 LND 지갑을 준비하고 동기화를 확인하는 과정은 [다음 글](02-testnet-wallet-and-sync.md)에서 이어진다.
