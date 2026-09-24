# StatefulSet과 PVC

> LND의 영속성과 신원 요구를 Kubernetes 리소스로 번역한다

StatefulSet과 PVC



설계의 출발점

LND의 컨테이너 이미지는 교체 가능하지만 `/data/.lnd`는 노드 자체에 가깝다. Kubernetes는 이 둘을 Pod와 PVC로 분리한다. StatefulSet은 각 노드에 안정된 ordinal과 전용 claim을 만들고, Service는 교체된 Pod에 같은 논리 주소를 제공한다.



왜 Deployment가 아닌가

Deployment도 PVC를 붙일 수 있다. 그러나 replica별 안정된 identity와 claim 관계를 기본 계약으로 제공하지 않는다. 이 프로젝트는 노드마다 `lnd-0-0 → data-lnd-0-0` 관계를 검사하고, regtest의 두 노드를 명시적으로 구분한다. StatefulSet의 순서 보장보다 **안정된 이름과 전용 storage identity**가 핵심 이유다.

sidecar가 같은 Pod에 있는 이유

`lndmon`과 payment collector는 loopback RPC와 readonly macaroon을 사용한다. 같은 Pod와 PVC의 read-only mount를 쓰면 macaroon을 Kubernetes Secret으로 복제하거나 네트워크에 별도 RPC 경로를 열지 않아도 된다. 반면 sidecar 장애가 Pod readiness와 자원 경합에 영향을 줄 수 있고, upstream 이미지가 UID 0으로 시작하는 호환성 예외가 Pod 전체 보안 설계에 남는다.

NetworkPolicy의 역할

기본 거부 후 DNS, Prometheus scrape, regtest Bitcoin RPC/ZMQ, peer P2P, testnet Neutrino만 허용한다. Service는 도달 가능한 이름을 만들 뿐 접근 권한을 만들지 않는다. NetworkPolicy는 노드가 필요한 통신만 표현하지만, CNI 구현과 host firewall을 대신하지 않는다.

| 요구사항 | 선택 | 대안 | 선택 이유 | 비용·한계 |
| --- | --- | --- | --- | --- |
| 노드별 안정된 storage identity | StatefulSet + claim template | Deployment + 고정 PVC | 이름과 claim 관계가 선언적 | 수평 복제가 노드 복제 의미는 아님 |
| 관측 자격 증명 최소화 | 동일 Pod의 readonly sidecar | 중앙 collector에 macaroon 배포 | 비밀 이동 범위를 줄임 | Pod 결합도와 자원 경합 |
| 로컬 개발 영속 볼륨 | K3s local-path | 분산 storage | 단일 노드에 단순하고 재현 가능 | 노드 장애 HA 없음 |
| 네트워크 경계 | default deny + 명시적 allow | 전체 egress 허용 | 필요 흐름을 코드로 증명 | 외부 peer 목적지는 넓은 CIDR |

Pod 재생성과 복구는 다르다

Pod 재생성은 같은 PVC로 프로세스를 다시 시작한다. 호스트 디스크 손실은 PVC 자체를 잃는 사건이다. SCB 복구는 별도 PVC에서 seed와 SCB를 사용하며 기존 노드와 동시에 실행하지 않는다. 이 세 경로를 하나의 “restart”로 묶으면 중복 신원과 잘못된 복구 판단이 생긴다.

| 실패 | 남아 있는 상태 | 첫 판단 | 대응 계층 |
| --- | --- | --- | --- |
| Pod 종료 | PVC | controller가 같은 claim으로 재생성하는가 | StatefulSet |
| wallet locked | PVC와 프로세스 | 저장 손실이 아니라 수동 unlock 대기인가 | LND runbook |
| node/guest 중단 | local-path disk | host가 돌아올 수 있는가 | host 운영 |
| PVC 삭제·disk 상실 | SCB·aezeed | 원래 node가 완전히 중지됐는가 | 격리된 recovery |
| DB 손상 | 원본과 백업 상태 | 임의 copy가 최신인지 추측하지 않음 | 공식 복구 절차 |
| telemetry 중단 | 업무 상태 미상 | 0이 아니라 unavailable로 처리 | monitoring runbook |

구현 근거

- `charts/lnd-ops/templates/lnd.yaml`: StatefulSet, claim template, sidecar, securityContext
- `charts/lnd-ops/templates/networkpolicy.yaml`: 기본 거부와 허용 흐름
- `ops/redeploy-check`: pubkey, channel, PVC UID, SCB, Prometheus sample의 재배포 전후 비교
- Kubernetes StatefulSet 공식 문서
- Kubernetes Persistent Volume 공식 문서

읽기 전용 관찰



점검 문제
같은 PVC UID를 확인하는 이유는 무엇인가?이름이 같은 새 PVC가 만들어져도 데이터 연속성은 없다. UID는 재배포 전후에 동일한 Kubernetes storage 객체인지 구분한다.
lndmon을 중앙 Deployment로 분리하면 어떤 새 위험이 생기는가?각 노드의 TLS 인증서와 readonly macaroon을 중앙 workload로 전송·마운트해야 하며 RPC 네트워크 경로와 권한 범위가 넓어진다.

면접 질문
> 단일 노드 local-path에서 StatefulSet을 썼다는 사실만으로 고가용성을 주장할 수 없는 이유와, 다중 노드로 옮길 때 먼저 바꿔야 할 계약은 무엇인가?
