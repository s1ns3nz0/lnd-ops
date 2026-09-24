---
title: Kubernetes 심층 방어
description: NetworkPolicy, RBAC, Kyverno, Falco가 서로 다른 실패 단계를 다루는 이유
versions: Kubernetes 1.36 · Kyverno 3.9.1 · Falco 9.2.0 chart
platforms: macOS arm64 · Windows WSL2 amd64
verified: 2026-09-24
commit: 841692b
status: 실제 환경 검증됨
scope: regtest · testnet
---
# Kubernetes 심층 방어
<MetadataCard versions="Kubernetes 1.36 · Kyverno 3.9.1 · Falco 9.2.0 chart" platforms="macOS arm64 · Windows WSL2 amd64" verified="2026-09-24" commit="841692b" status="실제 환경 검증됨" scope="regtest · testnet" />

LND의 wallet 볼륨에 접근할 수 있는 프로세스와 Kubernetes 리소스를 변경할 수 있는 계정은 서로 다른 권한을 가진다. 한 가지 보안 도구를 설치했다는 이유로 두 경계가 모두 보호되지는 않는다. 이 장에서는 잘못된 Pod가 배포되고, 실행된 프로세스가 통신하거나 API를 호출하는 순서로 통제를 따라간다.

## 배경 1: 요청이 통과하는 세 가지 질문

보안을 읽을 때는 “누가 요청했는가”, “무엇을 할 수 있는가”, “그 요청 내용이 배포 규칙에 맞는가”를 구분한다. Kubernetes에서 ServiceAccount는 workload가 API를 호출할 때 사용하는 신원이고, RBAC는 그 신원에 허용된 리소스와 동작을 정한다. 그다음 admission 단계의 정책은 허용된 변경 요청이라도 내용이 배포 기준에 맞는지 검사할 수 있다. [ServiceAccount](https://kubernetes.io/docs/concepts/security/service-accounts/) · [Admission 단계](https://kubernetes.io/docs/reference/access-authn-authz/admission-controllers/)

예를 들어 gateway가 Pod를 조회할 수 있다는 것은 그 Pod 안에서 명령을 실행할 수 있다는 뜻이 아니다. API의 대상 리소스와 동작은 별도로 허용해야 한다. 반대로 노드 파일을 읽는 프로세스의 행동은 Kubernetes API 요청이 아닐 수 있으므로 RBAC만으로 통제되지 않는다. 어떤 통제를 선택할지는 공격이나 실수가 지나가는 경로에 달려 있다.

이 프로젝트에서 LND의 ServiceAccount token을 자동 마운트하지 않는 이유는 LND가 API를 호출할 필요가 없기 때문이다. 쓸모없는 자격 증명을 컨테이너에 넣지 않으면 프로세스 침해 때 사용할 수 있는 경로 하나를 줄인다. 하지만 이것만으로 LND의 RPC나 볼륨 접근까지 제한되는 것은 아니므로 다른 계층의 통제가 이어진다.

## 배경 2: 네트워크 정책은 양쪽 방향을 따로 본다

Pod가 NetworkPolicy의 ingress 또는 egress 격리 대상이 되면 해당 방향에서 허용되는 트래픽을 정책들의 합으로 판단한다. 출발지의 egress와 목적지의 ingress가 모두 격리된 경우 연결이 되려면 양쪽에서 허용되어야 한다. 한쪽에 allow 규칙을 추가했다고 다른 쪽의 제한까지 사라지는 것은 아니다. [NetworkPolicy 동작](https://kubernetes.io/docs/concepts/services-networking/network-policies/)

예를 들어 Prometheus가 exporter를 읽으려면 목적지의 metrics 포트에 대한 ingress뿐 아니라 출발지 egress도 맞아야 한다. 이름으로 접근한다면 DNS 질의 경로도 필요하다. 따라서 default deny를 적용한 직후 “모든 것이 끊겼다”면 실제 서비스 경로와 이름 해석 경로를 나누어 확인한다.

NetworkPolicy의 기본 역할은 네트워크 도달 범위를 제한하는 것이다. 그 포트로 연결한 사용자가 어떤 LND RPC를 실행할 수 있는지는 TLS와 macaroon 같은 애플리케이션 경계에서 다룬다. 이 차이를 알면 네트워크 허용을 곧 관리자 권한 허용으로 이해하는 실수를 피할 수 있다.

## 배경 3: 컨테이너 안의 root 권한을 여러 겹으로 줄이는 이유

Linux capability는 전통적인 root 권한을 나눈 단위다. capability 제거, privilege escalation 제한, seccomp의 시스템 호출 제한은 각각 다른 권한 경로를 줄인다. seccomp `RuntimeDefault`는 런타임 기본 프로파일을 쓰는 것이며 LND 업무 의미를 이해하는 규칙은 아니다. 이러한 필드는 프로세스의 실행 권한을 제한하며, 파일 소유권이나 RPC 권한 설정을 대신하지 않는다. [Pod securityContext](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/)

따라서 root로 실행되는 이미지에서 capability만 제거한 상태와, 검증된 비root UID로 최소 파일에만 접근하는 상태는 동일하지 않다. 아래에서 설명하는 현재 호환성 예외를 남긴 채 “non-root 완료”라고 표시하면 보호 수준을 과장하게 된다. 예외는 실제 이미지와 PVC 권한을 함께 수정하고 기동·재배포를 검증한 뒤 닫아야 한다.


## 먼저 보호할 자산과 신뢰할 주체를 정한다

보호 대상은 wallet·채널 데이터, RPC 자격 증명, SCB, 클러스터 관리 권한이다. 현재 host와 운영자 kubeconfig는 관리자 신뢰 경계에 있다. 이 계정을 탈취한 공격자로부터 같은 host 안의 모든 자산을 완전히 보호한다고 주장하지 않는다.

별도의 monitoring namespace는 관리와 정책 적용 범위를 나누지만 그 자체로 격리를 완성하지 않는다. 어떤 ServiceAccount가 API에 접근하고 어떤 Pod가 어떤 포트로 통신할 수 있는지가 함께 정의되어야 한다. 기준 문서는 [security baseline](https://github.com/s1ns3nz0/lnd-ops/blob/master/docs/security-baseline.md)이다.

## 배포 시점: Kyverno와 securityContext

예를 들어 실수로 privileged Pod나 hostPath를 추가했다고 하자. 사람이 리뷰에서 놓칠 수 있으므로 Kyverno가 보호된 namespace에 적용되는 admission 정책을 검사한다. digest 이미지, 자원 요청과 제한, seccomp, capability 제거 등의 계약을 배포 입구에서 강제한다.

이 검사는 애플리케이션의 행동을 읽어 악성 여부를 판정하지 않는다. 입장 조건을 만족한 컨테이너에도 취약점은 있을 수 있다. [`kyverno-policy.yaml`](https://github.com/s1ns3nz0/lnd-ops/blob/master/charts/security/kyverno-policy.yaml)과 실제 workload의 securityContext를 함께 읽어야 어떤 조건이 강제되는지 알 수 있다.

현재 LND·lndmon·Python 이미지에는 UID 0 호환성 예외가 남아 있다. privilege escalation과 capability를 제한했어도 non-root 실행과 동일한 상태는 아니다. UID 0으로 시작하는 이미지에 `runAsNonRoot`만 켜면 컨테이너 시작이 거부될 수 있다. 실제 실행 UID를 바꾼 뒤에도 기존 PVC 파일 소유권이 맞지 않으면 LND가 데이터를 읽거나 쓰지 못하므로 두 조건을 나누어 검증해야 한다.

## 실행 시점: RBAC와 NetworkPolicy

LND 자체가 Kubernetes API를 호출할 이유는 없으므로 전용 ServiceAccount의 token 자동 마운트를 끄고 RoleBinding을 주지 않는다. 반면 runbook gateway는 Kubernetes를 읽어야 하므로 제한된 Role을 가진다. RBAC는 이 API 권한을 제한한다.

프로세스가 다른 Pod의 LND RPC에 접속하는 것은 별도 문제다. 이 경로에는 NetworkPolicy를 사용한다. 기본 ingress/egress를 거부한 뒤 DNS, scrape, Bitcoin과 peer 통신을 허용한다. NetworkPolicy는 여러 정책의 허용 규칙이 합쳐지는 모델이므로 넓은 allow 규칙 하나가 의도보다 큰 범위를 열 수 있다. 또한 지원하는 네트워크 구현이 실제 집행해야 한다. 정책 객체의 존재와 연결 차단 시험을 함께 보는 이유다. [공식 동작 설명](https://kubernetes.io/docs/concepts/services-networking/network-policies/)을 참고한다.

같은 Pod 안의 LND와 sidecar는 네트워크 경계를 공유한다. NetworkPolicy로 둘 사이의 localhost 통신을 세분화한다고 설명하면 안 된다. 외부 peer의 목적지 IP를 넓게 허용하는 정책도 남아 있으므로, 현재 구현을 목적지 인증이나 완전한 외부 전송 차단으로 표현하지 않는다.

## 실행 이후: Falco를 넣은 이유

admission을 통과한 workload가 예상 밖의 프로세스나 시스템 호출을 일으킬 수 있다. Falco는 노드의 runtime event를 관측하는 탐지 계층이다. 이 프로젝트에서는 명시적인 테스트 marker를 발생시켜 Falcosidekick, Prometheus, Alertmanager로 이어지는 경로를 시험한다.

탐지는 자동 차단과 다르다. marker가 전달됐다는 것만으로 LND 관련 모든 악성 행위의 rule coverage가 충분하다고 말할 수도 없다. 센서 자체가 높은 host 권한을 필요로 한다는 비용도 있다. Falco의 namespace를 분리하는 것은 정책과 운영 범위를 구분하기 위한 선택이며, 센서의 host 접근 권한 자체를 격리하지는 않는다. 이미지와 배포 구성 고정은 예기치 않은 변경을 줄이는 통제다.

## 통제가 실패했을 때 무엇을 기대하는가

잘못된 Pod spec은 admission에서 거부되고, 정상 Pod가 API 권한 밖의 요청을 하면 RBAC에서 거부되며, 허용되지 않은 통신은 네트워크 계층에서 차단되어야 한다. 그와 별도로 활성화된 탐지 규칙에 해당하는 runtime 행위는 탐지 경로에 나타나야 한다. 이 예상 결과를 각각 시험해야 도구 목록이 보안 설계가 된다.

```sh
kubectl -n lnd-testnet get serviceaccount lnd-node -o yaml
kubectl -n lnd-testnet get networkpolicy
kubectl get clusterpolicy lnd-ops-workload-baseline
```

위 조회는 선언된 통제를 확인한다. 실제 부정 테스트는 [`ops/verify-security`](https://github.com/s1ns3nz0/lnd-ops/blob/master/ops/verify-security)에 있으며 일회성 probe를 만들기 때문에 순수 읽기 명령과 구분한다.

<details class="quiz"><summary>면접 질문: Kyverno와 Falco를 둘 다 두는 이유를 한 사건으로 설명한다면?</summary>Kyverno는 hostPath나 privilege 같은 배포 조건 위반을 막는다. 그 조건을 만족한 이미지의 프로세스가 침해된 뒤 나타나는 runtime 행위는 별도의 탐지 대상이다. 두 도구의 관측 시점과 책임이 다르다.</details>

다음 [SCB와 복구](/09-security/scb-recovery)에서는 예방과 탐지가 실패하거나 disk를 잃었을 때의 경계를 다룬다.
