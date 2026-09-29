# 지갑이 있는 프로그램을 Kubernetes에 올린다는 것

> Lightning 노드 운영 회고 1편 · Phase 1 · 2026-09-23~28 실습·보존 기록 기준

LND는 돈을 주고받는 프로그램이다. 프로그램을 다시 켜는 것뿐 아니라, 이전 지갑과 거래 상태를 그대로 이어 쓰는 것이 중요하다. 빈 저장 공간으로 다시 켜면 같은 프로그램이어도 이전 노드가 돌아온 것은 아니다.

그래서 첫 질문은 **“프로그램이 꺼졌다 켜져도 무엇이 남아 있어야 할까?”**였다. Mac에서는 Lima VM 안에 K3s를, Windows에서는 WSL 2 안에 K3s를 사용하는 구성으로 시작했다. 두 호스트는 각각 별도 클러스터와 지갑을 운영했다.

LND는 Lightning Network의 결제를 처리하는 프로그램이다. Bitcoin의 시험용 네트워크인 testnet에서 노드 사이에 채널을 만들고 돈을 주고받았다. 채널은 두 노드가 자금을 배치하고 결제 상태를 갱신하는 관계다.

금액 단위 sat는 Bitcoin의 작은 단위로, 1 BTC는 100,000,000 sat다. 여기서 사용하는 testnet·regtest 자금은 mainnet 자금과 구분한다.

## 먼저 여섯 가지 이름만 알면 된다

| 이름 | 쉽게 생각하면 | 실제 역할 |
|---|---|---|
| Node | 프로그램이 일할 컴퓨터 | Pod를 실행한다 |
| Namespace | 이름표가 붙은 구역 | 리소스를 묶는다 |
| Pod | 프로그램이 일하는 자리 | LND 컨테이너를 실행한다 |
| PVC | 보관함 사용 신청서 | 지갑 데이터를 저장할 볼륨을 요청한다 |
| StatefulSet | 자리와 보관함을 연결하는 관리자 | Pod 교체 뒤에도 저장 공간을 이어 쓴다 |
| Service | 접속 창구 | 대상 Pod로 연결을 전달한다 |

Kubernetes Node는 프로그램을 실행하는 컴퓨터다. Lightning 노드는 그 위에서 실행되는 LND와 그 지갑을 가리킨다. Kubernetes 컴퓨터 하나에서 서로 다른 LND 두 개를 실행할 수도 있다.

보관함은 이해를 돕는 비유다. 실제 데이터는 볼륨에 저장되고, PVC는 그 볼륨을 사용하겠다는 요청이다. PVC가 있다고 다른 디스크에 백업까지 생기는 것은 아니다.

## 프로그램과 보관함을 따로 생각하기

일반적인 웹 애플리케이션에서는 Pod를 교체하고 외부 데이터베이스에 다시 연결하면 일을 이어갈 수 있다. 이 lab의 LND는 지갑과 채널 상태를 자신의 데이터 디렉터리에 저장한다. 저장 공간을 새로 만들면 프로세스는 실행할 수 있어도, 기존 노드가 가진 채널을 그대로 이어받는 상황은 아니다.

그래서 처음부터 실행 단위와 데이터 단위를 나눴다. 컨테이너 이미지는 프로그램을 다시 실행할 재료이고, PVC는 그 프로그램이 계속 사용할 상태를 담는다. Git과 Helm으로 이미지·리소스 구성을 재현하는 것과 지갑 데이터를 복구하는 것도 구분해야 했다. Git 저장소를 복제해도 기존 지갑이나 채널 상태가 따라오는 것은 아니다.

Mac과 WSL은 이 구분을 시험하기 좋은 환경이었다. 두 곳에 같은 차트를 적용해도 각자의 볼륨에서 새 지갑을 만들면 서로 다른 노드가 된다. 두 노드가 같은 공유기를 사용한다는 사실도 지갑이나 Kubernetes API를 하나로 합치지 않는다.

## 연습용 네트워크에서 먼저 돈을 주고받기

regtest는 Bitcoin 블록 생성을 실습자가 통제할 수 있는 환경이다. 외부 faucet이나 공개 네트워크의 다음 블록을 기다리지 않고, 두 LND 사이에 채널을 만들고 결제를 시험하는 데 사용했다.

기본 차트에는 Bitcoin Core와 LND 두 노드를 구성하고, testnet은 별도 Namespace로 분리했다. Namespace는 실습 대상을 구분하는 경계이고, 실제 통신 제한은 NetworkPolicy로 설정했다. Namespace 생성 자체를 네트워크 격리로 해석하지 않았다.

저장된 2026-09-23 WSL 검증 기록에는 1,000,000 sat 채널에서 10,000 sat를 양방향으로 결제한 결과가 있다. 단위만 보면 큰 금액처럼 보이지만 regtest 실습 자금이다. 이 결과가 의미하는 것은 외부 라우팅 능력이 아니라, 우리가 통제하는 환경에서 채널과 결제 흐름을 재현했다는 것이다.

regtest의 연결은 다음처럼 구성했다.

```text
lnd-0 ── Lightning P2P 9735 ── lnd-1
  │                              │
  └── Bitcoin RPC·블록/거래 알림 ──┘
                   │
              Bitcoin Core
```

Bitcoin Core는 regtest 체인을 관리한다. 두 LND는 그 체인에서 채널 개설 거래의 확정을 확인하고, 서로는 Lightning 프로토콜로 통신한다. 한 노드가 다른 노드에게 10,000 sat를 보내면 채널 안의 정산 권리가 바뀐다. 반대로 보내는 시험까지 성공해야 두 방향을 모두 확인했다고 할 수 있다.

당시 증거에는 새 양방향 10,000 sat 실습 외에도 누적 결제 내역이 있었다. 한 노드의 송신 성공은 3건·70,000 sat, 다른 노드는 2건·20,000 sat였다. 이 누적값을 이번에 한 번씩 보낸 금액과 혼동하지 않았다. 실행 한 번의 결과와 지갑에 남아 있는 전체 이력은 조회 범위가 다르기 때문이다.

## Pod가 바뀌어도 같은 지갑 보관함 연결하기

testnet으로 이어지는 리소스 구조를 단순화하면 다음과 같다.

```text
Namespace: lnd-testnet
  StatefulSet: lnd-0
    Pod: lnd-0-0
      lnd 컨테이너 → PVC: data-lnd-0-0 → PV
  Service: lnd-0 → 위 Pod의 지정 포트
```

StatefulSet은 Pod의 안정적인 식별자와 저장 공간 연결을 관리하기에 적합하다. 다만 Lightning 노드의 신원은 Pod 이름이 아니라 지갑에 보관된 키에서 나온다. `lnd-0-0`이라는 이름을 그대로 사용해도 다른 지갑을 연결하면 다른 Lightning 노드다.

StatefulSet의 안정적인 식별자·스토리지 동작은 [Kubernetes 공식 설명](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/)과 맞춰 확인했다.

PVC 역시 백업과 같은 뜻은 아니다. Pod가 교체되어도 같은 볼륨을 연결하는 것과, 실제 디스크를 잃었을 때 복구하는 것은 다른 문제다. 이 단계에서는 영속성을 구성하고, 복구 자체는 별도 검증 대상으로 남겼다.

실제 `charts/lnd-ops/templates/lnd.yaml`에서 LND 컨테이너는 다음처럼 저장 공간을 연결한다. 필요한 부분만 발췌했다.

```yaml
volumeMounts:
  - {name: data, mountPath: /data}
```

`name: data`는 연결할 볼륨 이름, `mountPath: /data`는 프로그램이 그 볼륨을 볼 위치다. 같은 template의 실행 인자 `--lnddir=/data/.lnd`는 “지갑과 노드 데이터를 이 위치에서 사용하라”는 뜻이다.

```text
LND가 /data/.lnd에 기록
  → /data에 연결한 볼륨에 저장
  → Pod가 교체돼도 같은 PVC를 연결하면 기존 데이터 사용
```

이 조각만 적용하는 것은 아니다. 실제 chart에는 어떤 볼륨을 만들지 정하는 `volumeClaimTemplates`도 함께 들어 있다.

저장 공간에 관여하는 세 리소스는 비슷해 보여도 담당하는 일이 다르다.

| 리소스 | 실제로 답하는 질문 | 확인할 내용 |
|---|---|---|
| StorageClass | 어떤 방식으로 볼륨을 마련하는가 | 기본 class와 provisioner |
| PVC | 이 프로그램이 어떤 저장 공간을 요구하는가 | 요청 크기, 접근 방식, Bound 여부 |
| PV | 요청과 연결된 볼륨은 무엇인가 | 연결된 claim, 저장 위치와 수명 정책 |

이 차트는 `storageClassName`을 직접 지정하지 않는다. 따라서 기본 StorageClass가 있는지 먼저 확인해야 한다. PVC가 Pending이라면 LND부터 고치기보다 저장 공간 요청을 처리할 provisioner와 이벤트를 살펴보는 것이 순서다.

```bash
kubectl get storageclass
kubectl -n lnd-testnet get pvc
kubectl -n lnd-testnet describe pvc data-lnd-0-0
```

`describe pvc`에서 `Used By`는 어느 Pod가 이 claim을 사용하는지, `Events`는 왜 볼륨 연결이 지연되는지 알려준다. `Bound`는 요청과 볼륨이 연결됐다는 뜻이다. 요청 용량 30Gi가 보인다고 호스트 디스크에도 항상 그만큼 여유 공간이 있다는 의미는 아니다. 특히 단일 노드의 로컬 저장 공간에서는 호스트 디스크 상태도 같이 봐야 한다.

## Service는 바뀌지 않는 접속 창구다

LND Service에는 관리용 RPC 10009와 Lightning P2P 9735 포트를 연결했다. ClusterIP는 클러스터 내부의 접속 지점이다. Service가 있다는 이유만으로 집 밖의 노드가 공유기를 지나 들어올 수 있는 것은 아니다.

Service 종류별 노출 범위는 [Kubernetes Service 문서](https://kubernetes.io/docs/concepts/services-networking/service/)를 참고했다.

이 구분은 이후 Mac·WSL 실습에서 중요해졌다. 클러스터 안에서는 Service와 EndpointSlice를 보고, 호스트 사이에서는 VM·WSL·공유기 경로를 따로 확인해야 했다. 관리용 RPC와 공개 P2P도 같은 노출 대상으로 취급하지 않았다.

```bash
kubectl get nodes -o wide
kubectl get storageclass
kubectl -n lnd-testnet get statefulset,pod,service,pvc -o wide
```

내가 이 명령에서 보려던 것은 리소스가 존재하는지뿐만이 아니었다. Node가 Ready인지, PVC가 Bound인지, 실제로 어떤 Pod에 연결되어 있는지를 확인했다.

Service와 Pod 사이에는 label 선택 관계가 있다. 이 lab의 Service는 `app.kubernetes.io/name: lnd-0`인 Pod를 대상으로 삼는다. Service 이름을 DNS로 찾으면 내부 접속 주소를 얻고, Service의 포트로 들어온 연결이 대상 Pod의 `targetPort`로 전달된다. Service 자체가 LND 프로그램을 실행하거나 지갑을 저장하는 것은 아니다.

```text
클러스터 내부 클라이언트
  → lnd-0.lnd-testnet.svc:10009
  → Service가 선택한 endpoint
  → lnd-0-0 Pod의 LND RPC:10009
```

어느 Pod를 선택했는지는 다음처럼 따로 볼 수 있다.

```bash
kubectl -n lnd-testnet get service lnd-0 -o yaml
kubectl -n lnd-testnet get endpointslices \
  -l kubernetes.io/service-name=lnd-0 -o wide
kubectl -n lnd-testnet get pods --show-labels
```

Service는 존재하지만 endpoint가 없으면 label이 맞지 않거나 대상 Pod가 준비되지 않은 상황을 의심할 수 있다. endpoint가 있어도 LND가 해당 포트에서 요청을 처리하는지, NetworkPolicy가 경로를 허용하는지는 별도로 확인한다.

외부 P2P는 경로가 더 길다. 이후 router 옵션을 켠 단계에서는 공개 TCP 9735를 호스트로 전달한 다음 VM 또는 WSL의 NodePort 30973을 거쳐 LND의 9735로 연결하는 구성을 사용했다. ClusterIP를 만드는 단계, NodePort를 여는 단계, 호스트와 공유기의 전달 경로를 구성하는 단계를 하나의 작업으로 생각하면 어디가 막혔는지 찾기 어려웠다.

NetworkPolicy는 이 경로의 허용 범위를 정한다. 기본 차트는 ingress·egress를 먼저 차단하고 DNS, regtest 내부 연결 또는 testnet의 필요한 외부 포트를 조건부로 허용한다. 이 정책은 네트워크 플러그인이 집행해야 효과가 있으며, Service 생성 자체가 허용 정책을 대신하지는 않는다.

## 실습 장비와 클러스터 자원

Mac과 Windows PC를 각각 독립적인 실습 호스트로 사용했다. 물리 장비의 CPU·전체 메모리, VM에 할당한 자원, 컨테이너의 requests·limits는 서로 다른 숫자이므로 구분해서 기록한다.

| 항목 | Mac 환경 | Windows·WSL 환경 |
|---|---|---|
| 호스트 OS·아키텍처 | macOS, arm64 | Windows 11 Home, amd64 |
| Kubernetes 실행 위치 | Lima VM 안의 단일 노드 K3s | WSL 2 Ubuntu 안의 단일 노드 K3s |
| 게스트 OS 설정·검증 기록 | 현재 Lima template은 Ubuntu 26.04 arm64 이미지 사용 | 당시 검증 기록은 Ubuntu 24.04 계열 |
| 게스트 CPU | 현재 Lima template 설정 4 vCPU | 실제 할당값 확인 대기 |
| 게스트 메모리 | 현재 Lima template 설정 8GiB | 실제 할당값 확인 대기 |
| 게스트 디스크 | 현재 Lima template 설정 80GiB | 실제 가상 디스크 크기·여유 공간 확인 대기 |
| 물리 CPU 모델·전체 RAM | 사용자 확인 대기 | 사용자 확인 대기 |

Mac의 4 vCPU·8GiB·80GiB는 `ops/lima.yaml.in`에 적힌 **VM 생성 설정**이다. Mac 본체의 총 CPU·메모리·SSD 사양이 아니며, 기존 VM의 현재 할당을 다시 조회한 결과도 아니다. WSL runbook에는 CPU 8개·RAM 16GiB·디스크 여유 100GiB 이상이라는 실습 권장 조건이 있지만, 이를 실제 장비의 측정 사양으로 옮기지 않았다.

LND testnet PVC의 30Gi와 Prometheus PVC의 10Gi도 별도의 물리 디스크가 있다는 뜻은 아니다. 각 workload의 저장 공간 요청이며, 실제 저장소는 VM·WSL과 호스트의 디스크 환경에 의존한다. LND 컨테이너의 메모리 limit 2Gi 역시 Mac VM 전체 메모리 8GiB와 다른 범위다.

이 환경 표는 성능 벤치마크의 조건을 뜻하지 않는다. Mac·WSL에서 노드·채널·관측을 실습한 실행 환경을 설명하기 위한 것이며, Loop 성공·실패를 CPU나 메모리 차이의 결과로 판단하지 않았다. 물리 장비 정보와 실제 게스트 할당은 확인된 뒤 확정할 항목이다.

## 다시 켠 뒤 무엇을 비교했나

2026-09-23 regtest 재배포 기록에서는 Helm을 다시 적용한 뒤 두 노드의 공개키, 채널, LND PVC UID, Prometheus PVC UID와 과거 지표 샘플을 비교했다. 이것은 같은 클러스터에서 기존 리소스를 유지한 재적용 검증이다. 클러스터나 PVC를 삭제한 뒤에도 자동 복구된다는 증거로 확대할 수는 없다.

이 실습 이후부터는 `Running`을 시작점으로 보게 됐다. 지갑이 있는 서비스의 배포 성공은 기존 데이터와 연결 관계가 유지됐는지까지 확인해야 설명할 수 있었다.

실습 근거: [WSL regtest 검증 기록](../evidence/windows-regtest-mvp-2026-09-23.md), [Kubernetes 설계 정리](../1-kubernetes%20design.md). [다음 편](01a-helm-chart-and-templates.md)에서는 이 리소스들을 만드는 Helm Chart의 values와 template을 살펴본다.
