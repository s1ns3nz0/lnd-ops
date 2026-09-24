---
title: 운영 요구 도출
description: LND의 상태와 실패 모델을 플랫폼 요구사항으로 번역한다
versions: LND pinned image · K3s 1.36.4
platforms: macOS arm64 · Windows WSL2 amd64
verified: 2026-09-24
commit: 841692b
status: 실제 환경 검증됨
scope: regtest · testnet
---
# 운영 요구 도출
<MetadataCard versions="LND pinned image · K3s 1.36.4" platforms="macOS arm64 · Windows WSL2 amd64" verified="2026-09-24" commit="841692b" status="실제 환경 검증됨" scope="regtest · testnet" />

| LND 특성 | 플랫폼 요구 | 실패 시 확인할 불변 조건 |
| --- | --- | --- |
| 장기 노드 신원과 wallet/channel DB | 안정된 PVC와 이름 | pubkey와 PVC UID가 유지됨 |
| wallet 잠금 상태 | 수동 unlock 경계와 상태 관측 | 자동화가 암호를 저장하지 않음 |
| peer·체인 연결 | 최소 허용 egress와 동기화 지표 | sync, peer, channel을 따로 확인 |
| 방향성 있는 채널 잔액 | inbound/outbound 별도 관측 | 목표 금액 송수신 가능 여부 |
| SCB 변경 | PVC 밖 암호화 백업과 최신성 | live SCB와 기록된 백업 일치 |
| 운영 자동화 | 읽기 우선, 작은 mutation allowlist | 거부와 실행 모두 감사 가능 |

요구사항은 리소스 목록이 아니라 **복구 후에도 참이어야 할 조건**으로 쓴다. 이 원칙이 `ops/redeploy-check`, phase acceptance, evidence schema로 이어진다.

## 점검
<details class="quiz"><summary>“Pod Ready”가 노드 정상 운영을 증명하지 못하는 이유는?</summary>프로세스가 떠 있어도 wallet lock, chain sync 지연, peer 단절, channel inactive, 부족한 유동성이 남을 수 있기 때문이다.</details>

