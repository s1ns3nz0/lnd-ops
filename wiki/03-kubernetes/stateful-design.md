---
title: StatefulSet과 PVC
description: LND의 영속성과 신원 요구를 Kubernetes 리소스로 번역한다
versions: Kubernetes 1.36 · K3s 1.36.4
platforms: macOS arm64 · Windows WSL2 amd64
verified: 2026-09-24
commit: 841692b
status: 실제 환경 검증됨
scope: regtest · testnet
---

# StatefulSet과 PVC

<MetadataCard versions="Kubernetes 1.36 · K3s 1.36.4" platforms="macOS arm64 · Windows WSL2 amd64" verified="2026-09-24" commit="841692b" status="실제 환경 검증됨" scope="regtest · testnet" />

## 설계의 출발점

LND의 컨테이너 이미지는 교체 가능하지만 `/data/.lnd`는 노드 자체에 가깝다. Kubernetes는 이 둘을 Pod와 PVC로 분리한다. StatefulSet은 각 노드에 안정된 ordinal과 전용 claim을 만들고, Service는 교체된 Pod에 같은 논리 주소를 제공한다.

<ClientOnly>
  <MermaidDiagram label="LND StatefulSet, Service, PVC, 관측 sidecar와 네트워크 정책" :code="`flowchart TB
    SVC[Service lnd-0] --> POD[Pod lnd-0-0]
    STS[StatefulSet lnd-0] --> POD
    PVC[(PVC data-lnd-0-0)] -->|/data| POD
    POD --> L[LND]
    POD --> LM[lndmon readonly]
    POD --> PC[payment collector readonly]
    NP[default deny + allowlists] -. constrains .-> POD
    PROM[Prometheus] -->|8989 / 9092 / 9093| POD
  `" />
</ClientOnly>

## 왜 Deployment가 아닌가

Deployment도 PVC를 붙일 수 있다. 그러나 replica별 안정된 identity와 claim 관계를 기본 계약으로 제공하지 않는다. 이 프로젝트는 노드마다 `lnd-0-0 → data-lnd-0-0` 관계를 검사하고, regtest의 두 노드를 명시적으로 구분한다. StatefulSet의 순서 보장보다 **안정된 이름과 전용 storage identity**가 핵심 이유다.

## 이 chart의 두 노드는 replicas 두 개와 다르다

템플릿은 `lnd-0`, `lnd-1`이라는 두 StatefulSet을 만들고 각각 replicas를 1로 둔다. 그래서 Pod는 `lnd-0-0`, `lnd-1-0`이며 claim은 각각 따로 생긴다. 이는 한 노드를 복제해 가용성을 늘리는 구성이 아니라 서로 결제하는 독립 노드 두 개를 만드는 방식이다.

Kubernetes의 이름은 운영 대상의 위치를 정하고, Lightning의 pubkey는 프로토콜상 노드 신원을 정한다. 이름이 같아도 빈 지갑이면 다른 상태이고, 같은 지갑을 두 workload에 붙여도 안전한 HA가 되지 않는다. Kubernetes identity와 Lightning identity를 구분해야 scale이라는 단어를 잘못 적용하지 않는다.

현재 Service는 일반 ClusterIP이며, Service 이름으로 해당 노드에 접근한다. StatefulSet에서 흔히 사용하는 headless Service와 Pod별 DNS가 이 chart에 구현됐다고 가정하면 안 된다. 필요한 계약은 노드별 Service와 단일 replica의 대응 관계다.

## sidecar가 같은 Pod에 있는 이유

`lndmon`과 payment collector는 loopback RPC와 readonly macaroon을 사용한다. 같은 Pod와 PVC의 read-only mount를 쓰면 macaroon을 Kubernetes Secret으로 복제하거나 네트워크에 별도 RPC 경로를 열지 않아도 된다. 반면 sidecar 장애가 Pod readiness와 자원 경합에 영향을 줄 수 있고, upstream 이미지가 UID 0으로 시작하는 호환성 예외가 Pod 전체 보안 설계에 남는다.

### read-only라는 말의 두 범위

관측 프로그램이 사용하는 readonly macaroon은 LND API 호출 권한을 줄인다. read-only volume mount는 파일 수정을 막는다. 그러나 현재 전체 `/data`를 마운트하므로 sidecar가 읽을 수 있는 다른 민감 파일까지 모두 숨겨지는 것은 아니다. 별도 프로세스라고 완전한 보안 격리가 있다고 가정하지 않는다.

또한 LND 템플릿에 업무 상태를 검사하는 readiness probe는 현재 없다. Kubernetes Ready를 wallet·channel readiness와 동일시하지 않고 별도 verifier와 metric을 사용한다. 이 예외는 [운영 요구](/02-requirements/operational-requirements)에서 도출한 요구가 어느 계층에서 검사되는지 보여준다.

## NetworkPolicy의 역할

기본 거부 후 DNS, Prometheus scrape, regtest Bitcoin RPC/ZMQ, peer P2P, testnet Neutrino만 허용한다. Service는 도달 가능한 이름을 만들 뿐 접근 권한을 만들지 않는다. NetworkPolicy는 노드가 필요한 통신만 표현하지만, CNI 구현과 host firewall을 대신하지 않는다.

| 요구사항 | 선택 | 대안 | 선택 이유 | 비용·한계 |
| --- | --- | --- | --- | --- |
| 노드별 안정된 storage identity | StatefulSet + claim template | Deployment + 고정 PVC | 이름과 claim 관계가 선언적 | 수평 복제가 노드 복제 의미는 아님 |
| 관측 자격 증명 최소화 | 동일 Pod의 readonly sidecar | 중앙 collector에 macaroon 배포 | 비밀 이동 범위를 줄임 | Pod 결합도와 자원 경합 |
| 로컬 개발 영속 볼륨 | K3s local-path | 분산 storage | 단일 노드에 단순하고 재현 가능 | 노드 장애 HA 없음 |
| 네트워크 경계 | default deny + 명시적 allow | 전체 egress 허용 | 필요 흐름을 코드로 증명 | 외부 peer 목적지는 넓은 CIDR |

## Pod 재생성과 복구는 다르다

Pod 재생성은 같은 PVC로 프로세스를 다시 시작한다. 호스트 디스크 손실은 PVC 자체를 잃는 사건이다. SCB 복구는 별도 PVC에서 seed와 SCB를 사용하며 기존 노드와 동시에 실행하지 않는다. 이 세 경로를 하나의 “restart”로 묶으면 중복 신원과 잘못된 복구 판단이 생긴다.

| 실패 | 남아 있는 상태 | 첫 판단 | 대응 계층 |
| --- | --- | --- | --- |
| Pod 종료 | PVC | controller가 같은 claim으로 재생성하는가 | StatefulSet |
| wallet locked | PVC와 프로세스 | 저장 손실이 아니라 수동 unlock 대기인가 | LND runbook |
| node/guest 중단 | local-path disk | host가 돌아올 수 있는가 | host 운영 |
| PVC 삭제·disk 상실 | SCB·aezeed | 원래 node가 완전히 중지됐는가 | 격리된 recovery |
| DB 손상 | 원본과 백업 상태 | 임의 copy가 최신인지 추측하지 않음 | 공식 복구 절차 |
| telemetry 중단 | 업무 상태 미상 | 0이 아니라 unavailable로 처리 | monitoring runbook |

## 구현 근거

- [`charts/lnd-ops/templates/lnd.yaml`](https://github.com/s1ns3nz0/lnd-ops/blob/master/charts/lnd-ops/templates/lnd.yaml): StatefulSet, claim template, sidecar, securityContext
- [`charts/lnd-ops/templates/networkpolicy.yaml`](https://github.com/s1ns3nz0/lnd-ops/blob/master/charts/lnd-ops/templates/networkpolicy.yaml): 기본 거부와 허용 흐름
- [`ops/redeploy-check`](https://github.com/s1ns3nz0/lnd-ops/blob/master/ops/redeploy-check): pubkey, channel, PVC UID, SCB, Prometheus sample의 재배포 전후 비교
- [Kubernetes StatefulSet 공식 문서](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/)
- [Kubernetes Persistent Volume 공식 문서](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)

## 읽기 전용 관찰

```sh
kubectl -n lnd-testnet get statefulset lnd-0 -o wide
kubectl -n lnd-testnet get pod lnd-0-0 \
  -o jsonpath='{.spec.volumes[?(@.name=="data")].persistentVolumeClaim.claimName}{"\n"}'
kubectl -n lnd-testnet get pvc data-lnd-0-0 -o custom-columns=NAME:.metadata.name,UID:.metadata.uid,PHASE:.status.phase
kubectl -n lnd-testnet get networkpolicy
```

## 점검 문제
<details class="quiz"><summary>같은 PVC UID를 확인하는 이유는 무엇인가?</summary>이름이 같은 새 PVC가 만들어져도 데이터 연속성은 없다. UID는 재배포 전후에 동일한 Kubernetes storage 객체인지 구분한다.</details>
<details class="quiz"><summary>lndmon을 중앙 Deployment로 분리하면 어떤 새 위험이 생기는가?</summary>각 노드의 TLS 인증서와 readonly macaroon을 중앙 workload로 전송·마운트해야 하며 RPC 네트워크 경로와 권한 범위가 넓어진다.</details>

### 면접 질문
> 단일 노드 local-path에서 StatefulSet을 썼다는 사실만으로 고가용성을 주장할 수 없는 이유와, 다중 노드로 옮길 때 먼저 바꿔야 할 계약은 무엇인가?
