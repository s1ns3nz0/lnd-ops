# Phase 4 · Loop 유동성 실습

Phase 4는 testnet LND에 Loop를 연결하고 실제 Loop Out 또는 Loop In **1건의
SUCCESS**를 확인하는 단계다. 설치·인증·견적 조회만으로 완료 처리하지 않는다.
`INVOICE_SETTLED`도 아직 완료가 아니다. 서버·채널 유동성이나 확인 블록이 부족하면
현재 사유를 보여주고 PENDING으로 남긴다.

## 시작과 인증

`./lndops`에서 `4`를 선택한다. 이후 직접 돌아오려면 `loop` 메뉴 또는
`./ops/loop-operations`를 사용한다. 이전 Phase를 다시 실행하지 않는다.

```text
Loop 전용 인증 파일 준비
[1] 새로 생성 — 현재 testnet 노드의 Loop In·Out 실행용
[2] 기존 파일 경로 입력
[u] 기존 지갑 잠금 해제  [q] 돌아가기
```

새 생성은 현재 kubeconfig의 `lnd-testnet/lnd-0-0`에서 testnet identity와 지원 RPC를
확인하고, `yes` 확인 후 `lncli bakemacaroon`을 실행한다. 생성 파일은
`${XDG_STATE_HOME:-$HOME/.local/state}/lnd-ops/credentials/loop-<node>-<random>/loop.macaroon`에
저장한다. 디렉터리는 0700, 파일은 0600이며 기존 파일을 덮어쓰지 않는다.
인증 내용은 화면·Git·운영 기록에 출력하지 않는다. 생성된 경로는 설치 단계에 자동 전달한다.

이 인증은 **실제 결제·트랜잭션 서명이 가능한 credential**이다. Loop v0.35.0-beta의
일반 Loop In/Out과 회수 경로에 사용하는 RPC를 `ops/loop_credentials.py`에서 명시한다.
LND 전체 관리자 macaroon, 지갑 seed 내보내기, 채널 개설·종료 권한은 부여하지 않는다.
Instant Out·static-address·Taproot Asset 서비스의 전체 권한을 보장하는 프로필은 아니다.
예전 견적 전용 인증 파일은 실제 swap에 부족하므로 새로 생성·교체한다.

기존 파일은 직접 경로를 입력할 수 있다. 파일 내용이나 `admin.macaroon`을 입력하지 않는다.
설치가 실패해도 생성된 파일은 유지되므로 다음 시도에는 기존 파일을 선택하면 된다.

`ops/enable-loop`는 LND TLS 인증서와 전용 macaroon을 `lnd-loop-credentials` Secret에
등록하고 Loop를 활성화한다. LND PVC는 Loop에 마운트하지 않는다. Loop 자체 DB·인증 파일은
별도 `loop-data` PVC를 쓴다. LND 재배포 후 지갑이 잠기면 기존 unlock 절차가 필요하다.
Flux가 해당 release를 관리 중이면 직접 Helm 변경은 기존 guard에서 차단한다.

## 수동 swap

운영 화면에서 수동 Out 또는 In을 고르고 대상 채널과 금액을 선택한다.

- **Out:** 선택한 채널로 Lightning 잔액을 보내고 같은 LND의 온체인 지갑으로 받는다.
  채널의 수신 여력을 확보한다. 외부 수신 주소는 이 UI에서 받지 않는다.
- **In:** 같은 LND의 온체인 잔액을 사용해 Lightning 잔액을 받는다.
  마지막 peer를 지정한다. 같은 peer에 활성 채널이 여러 개면 특정 채널을 보장할 수
  없으므로 이 UI에서는 실행을 보류한다.

서버 최소·최대 금액, 채널 여력, 온체인 예약금, 견적을 확인한다. 금액이 작다는 이유로
사용자 입력을 자동으로 늘리지 않는다. 서버 비용·채굴 예상·채굴 시작 상한·라우팅 한도·
24시간 예산을 표시하고 `SWAP <금액>`을 입력해야 실행한다. 견적은 60초 후 만료된다.

채굴 시작 상한은 견적의 2배이며, 이 값과 서버 비용·라우팅 한도가 입력한 전체 수수료
시작 한도를 넘으면 실행하지 않는다. Out 선결제는 서버 비용 일부이므로 이중 합산하지
않고, 보수적으로 서버 비용과 선결제 중 큰 값을 예약한다.

## 자동 swap

기본 OFF다. 대상 채널, local 잔액 비율 하한·상한, 1회 최대 금액, 1회 수수료 시작 한도,
결제별 라우팅 한도, 최근 24시간 예산을 입력하고 `AUTO 1`을 승인한다.

- local 비율이 상한보다 높으면 Out, 하한보다 낮으면 In을 검토한다.
- 범위 중간값으로 이동하는 금액과 승인한 최대 금액 중 작은 값을 사용한다.
- 조건이 맞아도 최신 견적·서버 금액 제한·잔액·예산을 모두 통과해야 요청한다.
- **화면을 열어 둔 동안만** 10초 간격으로 조건을 검사한다. 호스트 서비스나 Kubernetes
  자동 작업을 설치하지 않는다. `q`/Ctrl+C는 새 자동 실행을 끈다.
- 한 요청이 제출되면 추가 자동 실행은 OFF다. 진행 중 swap은 계속 관찰하고, 첫 성공이면
  Phase 4 완료다. 실패·응답 미확인·견적 오류 뒤에는 자동 재시도하지 않는다.
- 프로세스가 강제 종료된 뒤 화면을 다시 열어도 자동 제출을 재개하지 않는다.
  사용자가 규칙을 다시 승인해야 한다. 이미 제출한 요청은 상태만 이어서 조회한다.

Loop 자체 Autoloop와 동시에 실행하지 않는다. 자체 Autoloop가 켜져 있으면 요청을 막는다.
자동 실습 중에는 다른 CLI에서 swap을 동시에 시작하지 않는다. 본 UI의 예산과
동시 실행 제어는 외부 CLI나 다른 운영자의 실행까지 강제로 제한할 수는 없다.

**예산은 새 요청을 시작하는 한도이지 자금 회수 비용의 절대 상한이 아니다.** Loop Out은
preimage 공개 후 거래를 확정하기 위해 `max_miner_fee`를 넘길 수 있다. 시작 전 이 제약을
표시한다. 최근 24시간의 예약 비용과 실제 초과 비용을 반영하며, 다음 요청의 예산 검사에서
차단한다. 날짜가 바뀌었다고 미완료 요청이나 예약이 사라지지는 않는다.

### 경로 시간 초과 후 수동 재시도

Loop Out의 결제 시도 제한은 기본 300초이며, 수동 실행 화면에서 1~1800초로
입력할 수 있다. 자동 실습은 기본값을 사용한다. 이미 보낸 HTLC의 해소나 온체인
확정 대기는 별도이므로 전체 swap이 이 시간 안에 끝난다는 뜻은 아니다.
제한 시간을 늘려도 외부 채널의 유동성이나 결제 성공을 보장하지 않는다.

`FAILED / FAILURE_REASON_OFFCHAIN`인 Loop Out은 모든 비용 필드가 있고,
LND에서 같은 hash의 결제 실패와 모든 조회 결제의 종료, 대상 채널 존재와 모든 조회 채널의 HTLC 없음이
확인될 때만 실제 비용으로 예산을 정산한다. 원래 예약금과 요청 기록은 보존한다.
조회 실패나 증거 누락 시 예약을 유지한다. 화면에 `예산: 실제 비용으로 정산 완료`가
표시되는지 확인한 뒤 `1`로 새 견적을 확인하고 수동 승인한다. 자동 재시도하지 않는다.
L402 인증 비용과 채널 개설 비용은 이 swap 예산과 별도다.
다른 결제나 HTLC가 진행 중이어도 보수적으로 예약을 유지한다.

## 진행 상태와 중복 방지

요청 전에 `lnd-testnet/lnd-ops-loop-operations` ConfigMap에 노드 공개키·namespace UID,
고유 label·요청 금액·한도·제출 의도를 저장한다. Kubernetes resourceVersion으로 동시
실행을 제어하며, 저장에 실패하면 swap 요청을 보내지 않는다. 인증·preimage는 저장하지 않는다.

Loop 응답이 끊기면 `SUBMITTING`을 유지한다. 같은 label의 실제 swap을 조회해 결과를
확인하며 **요청을 자동 재전송하지 않는다**. 기록을 못 찾는다고 실패로 간주하거나 기록을
삭제하지 않는다. 이때 추가 swap도 막는다. 운영자가 Loop daemon 기록을 확인해야 한다.

화면은 swap 상태·실제 비용·실패 사유와 현재 채널·온체인 잔액을 표시한다. `q`는 진행 중
swap의 취소가 아니다. 이미 시작한 swap의 회수·완료를 위해 LND와 Loop를 계속 유지한다.
운영 ConfigMap을 삭제해 중복 방지나 비용 기록을 초기화하지 않는다.

## CPU 아키텍처와 이미지

Loop v0.35.0-beta의 upstream Docker ARM64 manifest에는 x86-64 바이너리가 들어 있어
ARM64 K3s에서 `exec format error`가 발생했다. OCI manifest 표기만으로 실행 가능 여부를
판정하지 않는다. `loop-image/releases.json`에 고정한 공식 Linux 배포 파일의 SHA256과
ELF 아키텍처를 확인해서 유지보수 중인 digest-pinned Python Linux 이미지에 설치한다.

`ops/deploy`는 Loop가 활성화돼 있으면 `ops/build-loop --load-k3s`로 호스트 아키텍처의
이미지를 빌드·검사·로컬 K3s에 import하고 실제 이미지 digest를 Helm에 전달한다.
레지스트리에 push하지 않는다. ARM64와 AMD64 각각 `loop`·`loopd --version`과 ELF를 검사한다.
직접 Helm을 사용하면 `loop.image`에 이 helper가 반환한 digest 참조를 지정해야 한다.

이미 보안 Phase를 적용한 클러스터는 갱신된 `charts/security/kyverno-policy.yaml`을 적용해야
한다. 이 정책은 기존 docker.io digest 이미지 외에 `localhost/lnd-ops-loop@sha256:*`만
추가로 허용한다. 태그만 지정한 로컬 이미지나 다른 localhost 이미지는 허용하지 않는다.

Loop Deployment는 이전 Pod를 내린 뒤 새 Pod를 올리며, `loop getinfo` readiness가
통과해야 배포 완료가 된다. 설치 helper도 마지막에 `ops/verify-loop --ready`를 실행한다.

## 배포와 검사

서버는 `test.swap.lightning.today:11010`이며, Loop API는 Pod 내부 localhost에만 연다.
호스트 CLI는 `loop-health` 컨테이너 안에서 인증된 REST 호출을 수행한다. 인증서는
`/loop/testnet/tls.cert`, Loop macaroon은 `/loop/testnet/loop.macaroon`을 사용한다.
NetworkPolicy는 LND RPC·서버 연결·DNS·Prometheus scrape 경로로 제한한다.

```bash
# 설치·노드 연결 상태만 확인, swap을 생성하지 않음
ops/verify-loop --ready

# 실제 SUCCESS 1건을 포함한 Phase 완료 확인, swap을 생성하지 않음
ops/verify-loop

# 현재 운영 기록 (인증정보 없음)
kubectl -n lnd-testnet get configmap lnd-ops-loop-operations
```

L402 토큰의 자동 구매 한도는 기존처럼 0이다. 서버가 유료 토큰을 요구하면 실패를
표시하고 멈춘다. 이를 우회하려고 자동으로 지출 한도를 올리지 않는다.

테스트는 격리된 Linux 환경에서 RPC 응답 fixture로 승인·예산·잔액·중복 방지·실패 후
복구를 검증한다. 실제 testnet 서버의 유동성이나 swap 성공을 대신 증명하지 않는다.
최종 운영 성공은 해당 노드의 실제 Loop `SUCCESS` 응답으로만 판정한다. 같은 노드에서
이전에 CLI로 완료한 일반 Loop In/Out도 인정한다. 새 요청의 상태는 고유 label로 별도 추적한다.

구현 근거: [Loop v0.35.0-beta RPC](https://github.com/lightninglabs/loop/blob/v0.35.0-beta/looprpc/client.proto),
[서버·TLS 기본 설정](https://github.com/lightninglabs/loop/blob/v0.35.0-beta/loopd/config.go),
[lndclient macaroon DB](https://github.com/lightninglabs/lndclient/blob/v0.21.0-2/macaroon_service.go).
