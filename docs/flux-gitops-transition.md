# Phase 8 · Flux GitOps 전환

`lndops`의 `gitops` 메뉴 또는 Phase 8에서 Flux 설치, Git 연결, 테스트 release의
실패·복구, 기존 testnet Helm release 인계를 진행한다. 설치 버전은 **Flux v2.9.5**다.
controller image는 Linux amd64/arm64 공통 manifest digest로 고정했다.

현재 노드를 끄거나 채널을 닫을 필요는 없다. 라우팅 화면의 `q`는 화면만 닫는다.
최초 인계에는 설정 변경을 섞지 않지만, 실제 Helm reconciliation에서 Pod 재시작이
발생하면 지갑 unlock과 동기화를 확인해야 한다. 지갑 암호를 자동 저장하지 않는다.

## 단계와 운영 범위

| UI Phase | 내용 |
|---|---|
| 1–7 | 노드·라우팅·관측·보안·백업 및 복구 |
| 8 | Flux GitOps 전환 |
| 9 | 장애·경보 실습 |
| 10 | 제한된 kagent |
| 11 | Mac·WSL 재현성 |
| 12 | 포트폴리오 데모 |

과거 `ops/phase8-acceptance` 등의 명령·증거 파일 이름은 유지한다.
새 UI Phase 8의 검증 명령은 `ops/flux-phase verify-auto`다.

첫 대상은 **WSL의 기존 testnet `lnd-ops` release**다. regtest, 공유 관측·보안
release, kagent, 호스트 NAT는 이번 인계 대상에 포함하지 않는다.
Mac도 같은 명령의 `--host mac`으로 별도 경로와 cluster UID에 묶어서 준비할 수 있다.
Mac 설정을 WSL kubeconfig로 실행하면 UID 검사에서 중단한다.

Flux source-controller는 Git/chart를 읽고, kustomize-controller는 해당 호스트 경로의
리소스를 적용한다. helm-controller가 실제 Helm release를 관리하며,
notification-controller는 Flux 이벤트를 처리한다. 이미지 자동 업데이트 controller는 설치하지 않는다.
기본 설치 manifest의 controller RBAC에는 클러스터 관리 권한이 있으므로 추적 Git
branch의 변경 권한도 배포 권한으로 취급한다. 공유 release 전체를 자동 인계하지 않는다.

## 준비

호스트에 `python3`, `kubectl`, `helm`, `git`이 필요하다. Flux CLI는 필요하지 않다.
설치 manifest를 저장소에 보관하고 checksum을 검사한다. 이미지 pull에는 네트워크가 필요하다.
실행 전 kubeconfig가 의도한 WSL 클러스터인지 확인한다.

```bash
export KUBECONFIG="${XDG_STATE_HOME:-$HOME/.local/state}/lnd-ops/kubeconfig"
kubectl config current-context
kubectl get nodes
./lndops
```

메뉴에서 `gitops`를 입력하면 다른 Phase를 재실행하지 않고 전환 작업에 진입한다.
숫자 8은 기존 누적 Phase 검사를 거친다. 각 작업은 결과를 보여주고 메뉴로 돌아오며,
`4`로 상태를 재조회할 수 있다. 중계 화면은 `progress`로 다시 열 수 있다.
설치·연결·인계 작업은 해당 동작 이름을 입력해야 실행된다.

## 1. Git 파일 생성

아래 예시의 branch는 실제로 사용할 branch로 바꾼다.

```bash
ops/flux-phase prepare --host wsl --url https://github.com/s1ns3nz0/lnd-ops.git --branch main
```

생성 위치는 `gitops/clusters/wsl/`이다.

- `config.json`: Git URL·branch·host·cluster UID. 인증정보는 포함하지 않는다.
- `bootstrap.json`: GitRepository와 Flux Kustomization.
- `workloads/kustomization.yaml`: 이 호스트가 적용할 리소스 목록.
- `workloads/probe.json`: 지갑 없는 테스트 HelmRelease.
- `workloads/namespace.json`: 테스트용 namespace.

자동 commit/push는 하지 않는다. **생성 파일과 `charts/flux`, `charts/gitops-probe`,
`charts/lnd-ops`가 추적 Git branch에 있어야** reconciliation이 가능하다.
`git diff`와 `git status`로 검토하고 필요한 파일만 commit/push한 뒤 진행한다.
이미 생성된 설정을 `prepare`가 덮어쓰지는 않는다.

비공개 Git은 기존 `flux-system` namespace의 읽기 전용 인증 Secret을
`--secret-name NAME`으로 지정한다. 설치 후 운영자가 별도 보안 절차로 Secret을
준비하고 `connect`를 실행한다. 이 도구는 Secret 내용을 읽거나 생성하지 않는다.
SSH는 `ssh://git@host/path` 형식과 검증된 known_hosts가 필요하다.
URL에 토큰/암호를 넣거나 seed·macaroon·지갑 암호를 Git에 저장하지 않는다.

## 2. Flux 설치와 Git 연결

```bash
ops/flux-phase install --host wsl --confirm INSTALL
ops/flux-phase connect --host wsl --confirm CONNECT
ops/flux-phase status
```

설치는 CRD/RBAC/controller를 적용하고 rollout을 기다린다. 다른 버전의 기존 Flux는
자동 덮어쓰지 않는다. 재실행으로 같은 버전의 설치를 계속할 수 있다.
Git 연결은 지정된 호스트의 `workloads/`만 적용한다. `prune: false`와
`deletionPolicy: Orphan`으로 시작한다. 아직 LND HelmRelease는 생성하지 않는다.

## 3. 실제 Git 반영·실패·복구 확인

먼저 초기 baseline이 적용될 때까지 상태를 확인한다.

```bash
ops/flux-phase record-probe --host wsl --stage baseline --confirm RECORD-PROBE
ops/flux-phase stage-probe --host wsl --stage failure
```

`stage-probe`가 바꾼 `workloads/probe.json`을 검토·commit/push한다.
이 변경은 테스트 chart에만 의도적인 Helm 렌더 실패를 일으킨다.

```bash
ops/flux-phase record-probe --host wsl --stage failure --confirm RECORD-PROBE
ops/flux-phase stage-probe --host wsl --stage recovery
```

복구 변경도 검토·commit/push한 다음 확인한다.

```bash
ops/flux-phase record-probe --host wsl --stage recovery --confirm RECORD-PROBE
```

검사는 source revision, Kustomization 적용 revision, HelmChart의 source revision,
HelmRelease의 최신 적용 시도와 조건을 대조한다. 단순히 오래된 Ready를 읽고 성공하지 않는다.
실패 단계는 의도한 chart 오류를 확인하며, 성공 단계는 실제 ConfigMap 내용까지 확인한다.
세 단계가 서로 다른 Git revision으로 확인돼야 LND 인계를 허용한다.
결과는 `flux-system/lnd-ops-flux-exercise` ConfigMap에 저장한다.

## 4. 기존 LND 인계 파일 생성

먼저 [백업·복구 runbook](regtest-runbook.md)에 따라 UI Phase 7을 완료한다.
검사는 `${XDG_STATE_HOME:-$HOME/.local/state}/lnd-ops/evidence/phase5-acceptance-*.json`의
최신 통과 기록을 읽는다. 현재 백업은 다음 읽기 전용 명령으로 확인할 수 있다.

```bash
ops/backup-status-encrypted testnet lnd-0 --read-only
ops/router-backup-copy --status --json
```

현재 SCB의 암호화 사본과 외부 사본을 모두 확인해야 한다.
지갑은 unlock·동기화돼 있어야 하며, 채널 개설/종료가 진행 중이면 끝날 때까지 기다린다.
로컬 HEAD와 Flux가 읽은 commit이 같아질 때까지 Git 반영을 기다린다.
`charts/lnd-ops`와 `gitops/clusters/<host>` 아래의 생성 파일 전체가 clean해야 한다.
`export-lnd`부터 최초 `accept`까지는 새 채널 개설·종료를 잠시 미룬다. 중계 결제로
잔액이 변하는 것은 허용하지만 peer 연결이 끊겨 활성 상태가 바뀌면 재확인이 필요하다.

```bash
ops/flux-phase export-lnd --host wsl --confirm EXPORT-LND
```

모든 적용 values를 보존하고, 현재 chart의 서버 dry-run 렌더와 설치된 manifest를
대조한다. 백업 helper가 갱신하는 `lnd-backup-status` 데이터는 Helm lookup이 현재
데이터를 그대로 보존하는 경우만 허용한다. 그 외 차이가 있으면 인계를 중단한다. 사용자 credential 값이 발견돼도 내보내지 않는다.
PVC UID, 노드 공개키, 채널/활성 상태와 Helm revision을 인계 전 기록으로 남긴다.
`workloads/lnd.json`은 **suspend=true**로 생성된다. 이 파일과 갱신된
`kustomization.yaml`을 검토·commit/push한다.

suspended HelmRelease가 나타난 시점부터 기존 `ops/deploy`, payer 확장,
profile 삭제/reset 명령은 해당 release를 변경하지 못한다.
`ops/enable-router`, `ops/enable-loop`도 `ops/deploy`의 차단을 따른다.
조회·지갑 unlock·송금·채널 개설과 종료는 기존 운영 명령을 사용한다.

## 5. 인계 활성화와 완료 확인

```bash
ops/flux-phase adopt --host wsl --confirm ADOPT
```

대상 release 이름·target/storage namespace·values·인계 정책을 다시 대조한다.
준비 후 지갑/채널/Helm 설정이 바뀌면 중단한다. namespace에 소유권 표식을 먼저
남기고 로컬 `lnd.json`의 `suspend`를 false로 변경한다. **검토·commit/push해야 실제
인계가 시작된다.** Helm install/upgrade 실패는 재시도하며 자동 uninstall·force 교체를 요청하지 않는다.

```bash
ops/flux-phase accept --host wsl --confirm ACCEPT
ops/flux-phase verify --host wsl
```

최신 Git/controller/Helm 적용 상태와 기존 PVC UID·identity·채널 보존을 검증해야
Phase 8이 완료된다. 설치만 완료됐거나 Git 반영·지갑 unlock이 남았으면 PENDING이다.
`accept`는 최초 인계의 채널 보존 증거를 ConfigMap에 저장한다. 이후 정상적인 채널
개설·종료는 완료 증거를 무효화하지 않는다. `verify`는 이 기록과 현재 상태를 읽기 전용으로
검증하며 송금·채널 종료·백업 생성·Git push를 실행하지 않는다.

## 전환 후 설정 변경

배포 관련 values는 Git으로 변경한다. 예를 들어 다음 파일은 CPU 제한 변경이다.

```json
{"lnd":{"resources":{"limits":{"cpu":"3"}}}}
```

```bash
ops/flux-phase edit-values --host wsl --patch change.json
```

이 명령은 `workloads/lnd.json`만 수정한다. 검토·commit/push 후 Flux 반영을 확인한다.
Router 주소, 모니터링, Loop enabled 등의 설정도 같은 경로를 사용한다.
Loop credential 준비는 별도 작업이다. 노드 수·storage·profile 변경은 이 간단한
수정 명령에서 허용하지 않는다. 별도 보존 계획을 먼저 검토한다.

## 보류·실패 대응

`ops/flux-phase status`로 resource별 상태를 보고 필요하면 다음을 조회한다.

```bash
kubectl -n flux-system describe gitrepository lnd-ops
kubectl -n flux-system describe kustomization lnd-ops
kubectl -n flux-system describe helmrelease lnd-ops
```

- Source 실패: URL/branch, 네트워크, 기존 Secret을 확인한다.
- Chart 실패: Git의 chart 경로와 values를 수정한 후 다시 반영한다.
- LND 잠김: 기존 unlock 절차를 수행하고 `verify`를 다시 실행한다.
- 인계 전 비교 실패: release를 삭제하지 않는다. 설정 차이·실제 채널 변화를 검토하고
  최초 인계가 시작되지 않았다면 아래 명령으로 현재 baseline과 suspended 파일을
  다시 생성할 수 있다. 로컬·클러스터 양쪽 suspend=true이고 소유권 표식과 인계 이력이
  없어야 한다. 변경 파일을 검토·commit/push한 뒤 `adopt`를 다시 실행한다.

  ```bash
  ops/flux-phase export-lnd --host wsl --refresh --confirm EXPORT-LND
  ```
- 인계 후 문제: 먼저 Git에서 `suspend: true`로 변경하여 추가 Helm reconciliation을
  멈추고 원인을 조사한다. HelmRelease 삭제는 Helm uninstall을 유발할 수 있으므로
  삭제를 중지 방법으로 사용하지 않는다. `prune: false`는 수동 삭제를 보호하지 않는다.

인계를 당장 진행하지 않으려면 suspended 상태를 유지한 채 중단한다. 노드와 중계는
계속 동작하지만 직접 Helm 배포는 차단된 상태다. Helm CLI로 소유권을 되돌리는 작업은
이 Phase의 자동 기능이 아니다. 배포 관리자를 되돌릴 목적으로 HelmRelease를 삭제하지 않는다.

Git 장애로 suspend 변경 자체가 반영되지 않으면 운영자가 먼저 Kustomization을 멈춘 뒤
HelmRelease를 멈출 수 있다. 아래 명령은 현재 진행 중인 Helm 작업을 즉시 취소하는 명령은 아니다.

```bash
kubectl -n flux-system patch kustomization lnd-ops --type=merge -p '{"spec":{"suspend":true}}'
kubectl -n flux-system patch helmrelease lnd-ops --type=merge -p '{"spec":{"suspend":true}}'
```

Git의 `lnd.json`도 suspend=true로 맞춘 다음 네트워크·설정 문제를 해결한다.
Git을 다시 읽도록 Kustomization만 `suspend:false`로 patch하고, HelmRelease의 재개는
Git에서 검토한 suspend=false 변경으로 수행한다.
namespace 소유권 표식은 일시 정지 중에도 직접 Helm 변경을 차단한다.
Git 원복은 지갑 DB나 채널 상태를 과거로 돌리는 작업이 아니다.

## 검증과 다음 확장

`tests/integration_flux.py`는 digest로 고정한 Linux Kind 노드와 격리된 Git 서버에서
실제 controller 설치, Git 변경/실패/복구, 기존 Helm release 인계와 PVC·Pod·저장 데이터
보존을 시험한다. 사용자 클러스터와 자금 있는 LND를 사용하지 않는다. 인계 명령 경로에서는
LND RPC와 백업 증거만 명시적 fixture로 대체한다. 실제 LND 지갑·채널 보존의 최종
운영 증거는 대상 WSL에서 `accept`가 수행할 때 만들어진다.
unit tests는 잘못된 대상, 오래된 Ready/revision, 증거 누락, credential 내보내기,
직접 배포 충돌 등의 거부 경로를 확인한다.

새 클러스터의 `클러스터 → Flux bootstrap → 전체 인프라 → 지갑 → 라우팅` 설치 경로는
별도 확장이다. 이번 Phase는 기존 testnet release의 전환을 구현한다.

참고: [Flux HelmRelease](https://fluxcd.io/flux/components/helm/helmreleases/),
[GitRepository](https://fluxcd.io/flux/components/source/gitrepositories/),
[Flux v2.9.5](https://github.com/fluxcd/flux2/releases/tag/v2.9.5).
