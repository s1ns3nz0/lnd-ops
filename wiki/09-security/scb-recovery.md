---
title: SCB와 복구
description: 노드 재시작, PVC 상실, SCB 데이터 손실 복구를 구분한다
versions: LND pinned image · GPG
platforms: macOS arm64 · Windows WSL2 amd64
verified: 2026-09-24
commit: 841692b
status: 실제 환경 검증됨
scope: regtest · testnet
---
# SCB와 복구
<MetadataCard versions="LND pinned image · GPG" platforms="macOS arm64 · Windows WSL2 amd64" verified="2026-09-24" commit="841692b" status="실제 환경 검증됨" scope="regtest · testnet" />

Pod 재시작으로 돌아오는 장애와 지갑 볼륨 자체를 잃은 장애는 복구 입력이 다르다. 전자에는 기존 데이터가 있고, 후자에는 그 데이터가 없다. 이 장은 SCB가 어떤 상황을 위한 도구이며, 왜 복구 실습에서 원래 노드를 먼저 중지하는지 설명한다.

## 백업 파일 존재와 복구 가능성의 차이

파일 이름이 `channel.backup`이라고 해서 모든 최신 채널 상태를 담은 데이터베이스 복제본은 아니다. SCB는 채널 상대와 복구에 필요한 정보를 이용해 데이터 손실 복구를 시작하게 한다. seed와 필요한 암호는 별도로 확보해야 한다. 오래된 channel DB를 최신인 것처럼 사용하는 위험과 SCB 경로의 차이는 [LND 공식 복구 문서](https://docs.lightning.engineering/lightning-network-tools/lnd/disaster-recovery)에 설명되어 있다.

SCB 복구는 기존 채널을 계속 운영하는 HA 인계가 아니다. 상대 peer의 응답과 채널 종료, 온체인 처리에 의존하므로 시간도 외부 조건에 영향을 받는다. 파일을 복호화했다는 사실만으로 모든 자금을 이미 회수했다고 기록할 수 없다.

## 같은 PC에 암호화 복사하는 선택의 범위

현재 스크립트는 K3s의 LND 데이터 볼륨 밖에 암호화된 백업을 만든다. 잘못된 PVC 삭제 등 일부 사고에서 복구 자료를 분리할 수 있다. 암호화는 파일 노출 시 내용을 보호하기 위한 통제다.

하지만 host disk 상실, PC 도난, host 관리자 침해는 원본과 백업을 동시에 잃거나 영향을 줄 수 있다. 같은 PC 안의 다른 폴더는 별도의 물리적 장애 도메인이 아니다. 외부 매체 또는 다른 호스트로의 보관은 이후 운영자가 완성해야 할 단계이며, 현재 실습 성공이 그 단계를 대체하지 않는다.

## 복구 실습에서 중복 신원을 막는 이유

원래 LND와 복구 LND를 동시에 켜면 같은 identity의 서로 다른 상태가 peer와 상호작용할 수 있다. 따라서 [`ops/prepare-regtest-recovery`](https://github.com/s1ns3nz0/lnd-ops/blob/master/ops/prepare-regtest-recovery)는 원래 노드를 중지하고 별도의 recovery PVC를 사용한다. 기존 볼륨을 덮어쓰지 않는 것은 실패 시 조사할 원본을 보존하는 의미도 있다.

운영자가 seed와 SCB 복구를 수행한 후 [`ops/verify-regtest-recovery`](https://github.com/s1ns3nz0/lnd-ops/blob/master/ops/verify-regtest-recovery)는 신원, 채널 종료와 회수 결과를 확인한다. 최종 정리에서 recovery 노드를 내리고 원래 PVC를 다시 쓰는 동작은 regtest 실습의 수명주기다. 실제 재해 상황에서 오래된 원본 DB를 임의로 다시 켜도 된다는 일반 복구 지침은 아니다.

## 최신성을 별도 지표로 보는 이유

백업 파일이 있다고만 확인하면 이후에 만들어진 채널의 정보가 빠졌는지 놓칠 수 있다. 그래서 원본 SCB 존재, 기록된 백업, 원본과 일치하는 상태, 백업 나이를 구분한다. 이 프로젝트의 24시간 경보 기준은 운영 정책이며 모든 결제마다 SCB가 바뀐다는 뜻은 아니다.

암호화, 파일의 권한, 원본과의 일치, 실제 recovery exercise는 서로 다른 증거다. 각각 통과해야 무엇을 잃었을 때 어디까지 복구할 수 있는지 설명할 수 있다. 공개 시험 결과는 [Windows Phase 5 증거](https://github.com/s1ns3nz0/lnd-ops/blob/master/docs/evidence/windows-phase5-recovery-2026-09-24.md)에서 범위를 확인한다.

## 실행 전에 설명할 수 있어야 하는 것

이 페이지에서는 복구 명령을 복사해 즉시 실행하지 않는다. 원본 node가 중지되는 시점, 별도 PVC의 역할, 필요한 seed와 암호의 종류, peer가 응답하지 않을 때의 대기, 복구 후 확인할 자금 상태를 먼저 설명해 본다. 실제 변경은 [regtest runbook](https://github.com/s1ns3nz0/lnd-ops/blob/master/docs/regtest-runbook.md)의 절차를 따른다.

<details class="quiz"><summary>백업 암호화와 복구 시험이 통과했는데도 무엇이 남아 있을까?</summary>host 전체 상실에 대비한 독립 보관, 복구 입력의 실제 접근 가능성, 상대 peer와 온체인 조건에 따른 복구 시간, 정기 재검증이 남는다. 실습 성공의 장애 범위를 확대 해석하지 않는다.</details>

다음 [kagent 대응](/10-automation/observe-to-act)은 이처럼 되돌리기 어려운 조치를 왜 모델 권한 밖에 두는지 연결한다.
