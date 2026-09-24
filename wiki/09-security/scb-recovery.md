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

복구 실습은 원래 LND를 중지하고 별도 PVC에서 동일 seed와 SCB를 사용한다. 원래 노드와 복구 노드가 동시에 같은 identity로 실행되지 않는 것이 핵심 불변 조건이다. 성공은 프로세스 기동이 아니라 원래 pubkey, DLP force close, 온체인 자금 회수로 판정한다.

- 준비: [`ops/prepare-regtest-recovery`](https://github.com/s1ns3nz0/lnd-ops/blob/master/ops/prepare-regtest-recovery)
- 검증: [`ops/verify-regtest-recovery`](https://github.com/s1ns3nz0/lnd-ops/blob/master/ops/verify-regtest-recovery)
- 원본 복귀: [`ops/finish-regtest-recovery`](https://github.com/s1ns3nz0/lnd-ops/blob/master/ops/finish-regtest-recovery)

