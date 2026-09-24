---
title: 안전하게 시작하기
description: 읽기 전용 학습, 기존 클러스터 관찰, regtest 실습의 시작 조건과 안전 경계
versions: K3s 1.36.4 · kubectl 1.36.2 · Helm 4.1.4
platforms: macOS arm64 · Windows WSL2 amd64
verified: 2026-09-24
commit: 841692b
status: 실제 환경 검증됨
scope: regtest · testnet
---
# 안전하게 시작하기
<MetadataCard versions="K3s 1.36.4 · kubectl 1.36.2 · Helm 4.1.4" platforms="macOS arm64 · Windows WSL2 amd64" verified="2026-09-24" commit="841692b" status="실제 환경 검증됨" scope="regtest · testnet" />

## 배경지식부터 읽는 순서

클러스터가 없어도 읽을 수 있다. 첫 페이지는 [LND의 사용 사례와 전체 흐름](/01-foundations/lnd-workflow)이다. 송금·수신·중계가 무엇인지 보고, 두 노드가 지갑 준비부터 invoice 지급과 정산까지 가는 과정을 따라간다. 여기서는 Kubernetes나 채널 내부 거래를 먼저 알 필요가 없다.

그다음 [LND 구조](/01-foundations/lnd-architecture)에서 방금 본 흐름을 내부 구성과 연결하고, [채널과 유동성](/06-payments/channel-liquidity)에서 송수신 가능량을 계산한다. 이후 운영 요구와 Kubernetes, 관측, 보안, 자동 대응 순서로 읽는다. 자세한 순서는 [학습 지도](/roadmap)에 있다.

각 장의 수치 예시는 계산 원리를 배우기 위한 것이다. 현재 코드의 실제 임계값과 검증 결과는 별도로 표시한다. 설명을 이해한 뒤 구현 근거에서 해당 원리가 어떤 설정으로 표현됐는지 확인한다.

## 먼저 모드를 고른다

| 모드 | 필요한 환경 | 상태 변경 | 시작점 |
| --- | --- | --- | --- |
| 읽기만 | 브라우저 | 없음 | [학습 지도](/roadmap) |
| 기존 환경 관찰 | 배포된 lnd-ops와 kubeconfig | 없음 | 아래 읽기 전용 점검 |
| 로컬 regtest 실습 | 준비된 Mac 또는 Windows WSL2 | regtest만 변경 | [clean-start runbook](https://github.com/s1ns3nz0/lnd-ops/blob/master/docs/clean-start-runbook.md) |
| testnet 검증 | 자금·채널이 있는 기존 testnet 노드 | 기본 경로는 읽기 전용 | [testnet runbook](https://github.com/s1ns3nz0/lnd-ops/blob/master/docs/testnet-runbook.md) |

처음에는 **기존 환경 관찰**로 시작한다. 다음 명령은 Kubernetes나 LND 상태를 변경하지 않는다.

## 첫 읽기 전용 점검

```sh
cd ~/src/lnd-ops
export KUBECONFIG="${XDG_STATE_HOME:-$HOME/.local/state}/lnd-ops/kubeconfig"

kubectl config current-context
kubectl get nodes
kubectl -n lnd-regtest get statefulset,pod,pvc,service
ops/demo --to 3 --dry-run --no-color
```

기대 결과는 Kubernetes node가 `Ready`이고, LND Pod와 PVC 관계가 출력되며, 마지막 명령이 실행할 읽기 전용 1~3단계 계획을 보여주는 것이다. `Unauthorized`, `connection refused`, `Pending PVC`가 나오면 실습을 진행하지 말고 [Windows runbook](https://github.com/s1ns3nz0/lnd-ops/blob/master/docs/windows-runbook.md) 또는 [clean-start runbook](https://github.com/s1ns3nz0/lnd-ops/blob/master/docs/clean-start-runbook.md)에서 환경을 복구한다.

## 안전 규칙

1. 장애 주입과 복구는 regtest에서 먼저 수행한다.
2. seed, cipher seed passphrase, wallet password, macaroon, payment request를 문서·Git·로그·LLM 입력에 붙이지 않는다.
3. `delete`, wallet unlock, payment, channel open/close, recovery 명령은 해당 runbook의 선행 조건을 확인한 뒤 실행한다.
4. testnet에서는 명령이 읽기 전용인지 확인하고, 자금 이동은 운영자가 금액과 목적지를 직접 검토한다.
5. recovery namespace나 같은 pubkey의 두 LND가 보이면 추측해서 정리하지 않는다.

## 페이지 메타데이터 읽기

| 항목 | 의미 |
| --- | --- |
| 관련 버전 | 설명과 검증에 사용한 핵심 버전 |
| 검증 플랫폼 | 실제로 수행했거나 자동 검사한 환경 |
| 마지막 검증 | 코드 작성일이 아니라 근거를 다시 확인한 날짜 |
| 근거 커밋 | 설명한 acceptance/evidence가 통과한 Git revision; 문서 수정마다 자동 변경하지 않음 |
| 설계됨 | 의도와 경계가 문서화됐지만 실행 증거가 없음 |
| 자동 검증됨 | CI나 결정적 테스트가 통과함 |
| 실제 환경 검증됨 | 대상 Mac/Windows 클러스터에서 acceptance를 통과함 |
| 적용 범위 | regtest, testnet 중 어느 환경에 근거가 있는지 표시 |

## 완료 조건

- 현재 context와 API server가 의도한 로컬 클러스터다.
- node가 `Ready`다.
- Pod가 어떤 PVC를 쓰는지 설명할 수 있다.
- dry-run의 1~3단계가 왜 읽기 전용인지 설명할 수 있다.
- 비밀과 자금 조작이 학습 명령에서 분리됐음을 확인했다.

다음은 [LND의 사용 사례와 전체 흐름](/01-foundations/lnd-workflow)이다.
