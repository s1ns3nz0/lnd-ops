---
title: 지갑과 복구 경계
description: seed, password, macaroon, TLS, SCB의 서로 다른 보안 역할
versions: LND pinned image
platforms: macOS arm64 · Windows WSL2 amd64
verified: 2026-09-24
commit: 841692b
status: 실제 환경 검증됨
scope: regtest · testnet
---
# 지갑과 복구 경계
<MetadataCard versions="LND pinned image" platforms="macOS arm64 · Windows WSL2 amd64" verified="2026-09-24" commit="841692b" status="실제 환경 검증됨" scope="regtest · testnet" />

| 항목 | 보호하는 것 | 자동화 정책 |
| --- | --- | --- |
| aezeed | 온체인 키 복구 | 화면·파일·LLM 입력 금지, 운영자 기록 |
| wallet password | 로컬 DB unlock | 대화형 입력, 저장 금지 |
| macaroon | RPC 권한 | readonly만 관측 workload에 read-only 제공 |
| TLS cert | RPC 서버 신뢰 | 만료 관측, 수동 회전 |
| SCB | 채널 데이터 손실 복구 | 호스트에 암호화 복사, 최신성 검사 |

Vault를 쓰더라도 seed와 wallet unlock을 무조건 자동화해야 하는 것은 아니다. 이 프로젝트에서 Vault는 향후 중앙 비밀 수명주기 문제를 해결할 후보이며, 현재 단일 사용자 로컬 클러스터의 자금 조작 권한을 LLM이나 Pod에 넘기는 근거가 아니다.

근거: [`docs/testnet-runbook.md`](https://github.com/s1ns3nz0/lnd-ops/blob/master/docs/testnet-runbook.md), [`docs/security-baseline.md`](https://github.com/s1ns3nz0/lnd-ops/blob/master/docs/security-baseline.md)

