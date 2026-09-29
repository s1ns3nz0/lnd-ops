# Helm 설치 뒤에 남은 일: testnet 지갑과 동기화

> Lightning 노드 운영 회고 3편 · Phase 2 · 2026-09-24~28 실습·보존 기록 기준

가게 건물을 열었다고 바로 장사할 수 있는 것은 아니다. 금고를 준비하고 장부도 확인해야 한다. LND도 Pod를 실행한 뒤 지갑을 준비하고 네트워크 상태를 따라잡아야 한다.

regtest 다음에는 공개 Bitcoin testnet에 연결하는 지속 노드를 구성했다. 이 lab의 testnet 설정은 Neutrino backend를 사용한다. regtest의 로컬 Bitcoin Core 구성과 같은 방식으로 이해하면 안 됐다.

차트 구조와 values·template의 연결은 [이전 글](01a-helm-chart-and-templates.md)에서 자세히 다뤘다.

## 설치 다음에 하는 일의 순서

```text
LND 실행
  → 새 지갑이면 한 번 생성 / 기존 지갑이면 필요할 때 unlock
  → Bitcoin 장부와 Lightning 경로 정보 동기화
  → 입금·채널·방향별 잔액 확인
  → 시험 결제
```

`lncli`는 이 단계들의 상태를 물어보는 명령 도구다. `getinfo`는 상태를 물어보고, `walletbalance`는 온체인 지갑 잔액을 물어본다. 다른 명령에는 돈을 보내는 기능도 있으므로 모든 lncli 명령이 조회 전용인 것은 아니다.

## 명령을 어느 컴퓨터에 보내는지 먼저 확인하기

WSL에서는 kubeconfig 경로를 셸 변수에 넣었지만 export하지 않아 `kubectl`이 `localhost:8080`으로 접속하려다 실패한 적이 있었다. 다른 때에는 따옴표 안에 줄바꿈이 들어가 파일 경로 끝에 개행이 붙었다.

이후 터미널마다 다음 순서로 대상을 확인했다. 아래 경로는 lab에서 이미 준비한 kubeconfig 파일이다. 다른 환경에서는 자신의 파일 경로를 사용하며, `export`가 파일 자체를 생성하지는 않는다.

```bash
export KUBECONFIG="${XDG_STATE_HOME:-$HOME/.local/state}/lnd-ops/kubeconfig"
kubectl config current-context
kubectl get nodes -o wide
```

Mac과 WSL에 같은 이름의 Namespace와 Pod가 있어도 같은 클러스터는 아니다. context 이름만 믿기보다 실제 Node와 LND 공개키까지 비교했다. kubeconfig 환경변수를 설정하는 것은 현재 셸의 접속 대상을 고르는 일이고, 지갑을 이동시키는 작업이 아니다.

## 설치 설명서와 실제 설치값 비교하기

LND 차트는 이 프로젝트에서 작성한 `charts/lnd-ops`다. 기본값은 regtest 노드 두 개이고, `values-testnet.yaml`은 profile을 testnet으로 바꾸고 LND 한 개에 30Gi 저장 공간을 요청한다. 이 값은 lab의 선택이며 모든 Lightning 노드의 필수 용량은 아니다.

설정을 확인할 때는 소스 파일과 실제 Helm release를 함께 봤다. 소스에 적힌 기본값만으로 실행 중인 설정을 설명하면, 과거 배포 때 넣은 override를 놓칠 수 있기 때문이다.

```bash
helm list -n lnd-testnet
helm get values lnd-ops -n lnd-testnet --all
helm get manifest lnd-ops -n lnd-testnet
```

여기서 `lnd-ops`는 이 lab의 release 이름이다. 다른 환경에서는 `helm list` 결과의 이름을 먼저 사용해야 한다. values와 manifest에는 민감한 설정이 포함될 수 있어, 조회 결과 전체를 그대로 블로그에 올리지는 않았다.

## 지갑 생성과 잠금 해제는 무엇이 다른가

새 PVC로 시작한 LND에는 사용할 지갑이 없을 수 있다. 이때 한 번 지갑을 생성하고 복구 재료를 보관한다. 이후 같은 PVC를 붙인 Pod가 재시작돼 잠금 상태가 되면 기존 지갑을 unlock한다. 매번 새 지갑을 만드는 흐름이 아니다.

| 현재 상황 | 해야 하는 일 | 확인할 결과 |
|---|---|---|
| 지갑이 아직 없음 | 새 지갑 생성 | 지갑과 노드 identity가 생김 |
| 기존 지갑이 잠김 | 기존 암호로 unlock | 같은 identity로 RPC 사용 가능 |
| 지갑은 열렸지만 동기화 중 | LND 상태·backend 연결 확인 | 체인·그래프 상태가 진행됨 |
| 동기화 완료 | 자금·peer·채널 단계로 진행 | 송신·수신 준비를 별도로 확인 |

이 lab은 [지갑 생성 스크립트](../../ops/create-testnet-wallet)와 [기존 지갑 unlock 스크립트](../../ops/unlock-testnet)로 대화형 절차를 분리한다. 저장소 루트에서 사용하는 helper이며 아래 조회 코드보다 먼저 지갑 상태를 준비하는 단계다. 읽기 전용 `getinfo`가 실패한다고 즉시 create를 다시 실행하지 않는다.

실제 Pod와 컨테이너가 있는지, 지갑이 잠겼는지부터 구분해야 한다.

복구 재료의 역할도 다르다. seed는 지갑 키 복구의 바탕이고, 지갑 암호는 현재 지갑을 여는 데 쓴다. SCB는 채널 복구에 사용할 정적 백업이며 최신 채널 상태 전체의 복제본이 아니다. 이 lab에서 SCB를 파일로 암호화할 때 쓰는 암호 역시 지갑 암호와 별개다. seed만 가지고 기존 활성 채널을 그대로 재개할 수 있다고 이해하면 안 된다.

[LND 복구 문서](https://github.com/lightningnetwork/lnd/blob/v0.21.3-beta/docs/recovery.md)

## lncli는 LND에게 말을 거는 리모컨이다

자주 사용하는 명령을 짧게 만들기 위해 함수를 정의했다.

```bash
lnc() {
  kubectl --kubeconfig="$KUBECONFIG" -n lnd-testnet exec lnd-0-0 -c lnd -- \
    lncli --lnddir=/data/.lnd --network=testnet "$@"
}

lnc getinfo | jq '{identity_pubkey, block_height, synced_to_chain, synced_to_graph}'
```

일반 조회는 TTY가 필요 없어서 `exec -it`를 사용하지 않았다. JSON을 `jq`로 넘길 때 불필요한 터미널 제어와 출력 형태의 혼동도 줄일 수 있었다. 지갑 생성처럼 입력이 필요한 작업은 별도의 대화형 명령으로 다뤘다.

`lncli`만 설치하고 주소를 넣으면 송금할 수 있는 것은 아니다. 이 구성에서는 실행 중인 LND가 지갑과 네트워크 상태를 관리하고, `lncli`가 인증된 RPC로 작업을 요청한다. 지갑을 사용할 수 있게 된 뒤에는 LND가 설정된 backend를 통해 동기화를 수행한다.

이 함수에서 `--` 앞은 kubectl이 처리하고, 뒤는 컨테이너 안에서 실행하는 명령이다. `"$@"`는 `lnc walletbalance`의 `walletbalance`처럼 사용자가 넘긴 인자를 그대로 lncli에 전달한다. 여러 줄 함수를 입력하다 `>` 프롬프트가 나오면 보통 괄호나 따옴표가 아직 닫히지 않은 상태다. 지갑이 추가 입력을 요구하는 것과 셸이 명령 문장의 완성을 기다리는 것은 다르다.

## 장부와 길 안내 지도를 따로 따라잡기

체인 쪽에서 알아야 하는 것은 Bitcoin 블록과 지갑에 관계된 거래다. 채널 funding 거래가 확정됐는지, 내 지갑으로 들어온 돈이 있는지 판단하려면 이 정보가 필요하다. 이 lab의 testnet은 Neutrino라는 경량 backend를 사용하며, regtest처럼 같은 차트 안에 Bitcoin Core 전체 노드를 띄우지 않는다.

그래프 쪽에서 알아야 하는 것은 공개 Lightning 노드와 채널, 방향별 수수료·전달 조건이다. peer가 전파하는 정보를 이용해 결제 경로를 찾는다. 그래프가 있다고 각 채널의 실시간 잔액까지 모두 알려지는 것은 아니다. 그래서 그래프 동기화가 끝나도 실제로 보내 보면 중간 채널에서 실패할 수 있다.

[Lightning 그래프 전파 규격](https://github.com/lightning/bolts/blob/master/07-routing-gossip.md)

동기화는 별도의 “동기화용 LND”를 추가로 실행하는 작업이 아니다. 지갑을 사용할 수 있게 된 LND가 설정된 backend와 peer를 통해 수행한다. 사용자는 진행 상태와 오류를 확인한다. 이 lab의 runbook은 검토한 testnet peer에 연결하고 `listpeers`로 확인하는 절차를 별도로 둔다.

공개 DNS 후보 탐색이 비었을 때는 허용된 bootstrap peer로 그래프 정보를 확보하는 경로도 마련했다. 초기 연결 상대를 확보하는 일과 그 상대에게 자금을 넣어 채널을 여는 일은 별개의 승인 단계다.

```bash
lnc getinfo | jq '{identity_pubkey, block_height,
  synced_to_chain, synced_to_graph, num_peers}'
kubectl -n lnd-testnet logs lnd-0-0 -c lnd --tail=100
```

출력 항목은 다음처럼 읽으면 된다.

| 항목 | 쉽게 읽는 뜻 |
|---|---|
| `identity_pubkey` | 어느 Lightning 노드인가 |
| `block_height` | 현재 몇 번째 Bitcoin 블록까지 보고 있는가 |
| `synced_to_chain` | LND가 체인 동기화 상태를 완료로 보고하는가 |
| `synced_to_graph` | LND가 공개 경로 정보의 동기화를 완료로 보고하는가 |
| `num_peers` | 현재 연결된 Lightning 상대가 몇 개인가 |

`jq`는 LND를 설정하는 도구가 아니다. LND가 돌려준 JSON에서 위 항목만 골라 보기 좋게 보여준다. `kubectl logs`는 프로그램이 남긴 실행 기록을 읽는다.

블록 높이가 한동안 같다는 사실만으로 멈췄다고 단정할 수는 없다. 공개 네트워크의 다음 블록 자체가 아직 나오지 않았을 수도 있다. 반대로 `Running`인데 로그에 연결 오류가 반복되고 동기화가 진행되지 않는다면 backend와 네트워크를 살펴야 한다. 로그의 시간과 `getinfo` 결과를 같은 시점에 비교하는 이유다.

## 지도를 받았다고 보낼 돈까지 생기지는 않는다

`synced_to_chain`은 체인 동기화, `synced_to_graph`는 Lightning 그래프 동기화 상태를 확인하는 데 사용했다. 둘 다 true여도 채널과 송신·수신 여력이 자동으로 생기지는 않는다.

실습 중 WSL 출력에서는 두 값이 true인 상태를 확인했다. 2026-09-24 저장 기록에는 testnet 노드의 재시작 뒤 기존 공개키와 채널 peer가 유지된 결과도 남아 있다. 그 기록은 당시 검증이고, 이번 글 작성일에 새로 재시작한 결과는 아니다.

## 껐다 켠 뒤 같은 노드인지 확인하기

2026-09-24 WSL 기록은 Pod 재시작과 일반 Helm 재적용을 따로 다룬다. Pod 재시작에서는 Pod UID가 바뀌었지만 노드 identity, 기존 채널 funding point, 연결된 공개 peer가 유지되는지 확인했다. 당시 지갑 unlock을 포함해 복구 확인에 205초가 걸렸다. 이 숫자는 당시 결과이며 모든 재시작의 제한 시간은 아니다.

Helm 재적용에서는 LND와 Prometheus의 PVC UID, 채널 목록, SCB 사본의 무결성, 과거 Prometheus의 특정 시점 샘플도 비교했다. 프로그램이 새로 떠서 현재 값만 다시 수집한 것과 과거 이력까지 유지한 것을 구분하려고 확인 범위를 넓힌 것이다.

이 증거는 기존 클러스터와 PVC를 유지한 상황의 연속성을 보여준다. 디스크를 잃은 상황에서 seed와 SCB로 자금을 회수하는 복구 시험까지 대신하지는 않는다. 운영에서 “재시작 가능”과 “재해 복구 가능”을 같은 표현으로 쓰지 않게 된 지점이다.

이 단계에서 얻은 노드는 동기화된 지갑과 RPC를 가진 실행 환경이었다. 다음 단계에서는 온체인 잔액을 채널에 어떻게 배치하고, 그 잔액이 어느 방향의 결제에 쓰이는지 이해해야 했다.

실습 근거: [testnet values](../../charts/lnd-ops/values-testnet.yaml), [WSL testnet 검증 기록](../evidence/windows-testnet-phase1-2026-09-24.md), [testnet runbook](../testnet-runbook.md).
