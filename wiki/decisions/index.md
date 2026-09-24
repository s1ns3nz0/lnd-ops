---
title: ADR 색인
description: 시스템 전체에 영향을 주는 기술 선택과 대안
versions: Project architecture
platforms: macOS arm64 · Windows WSL2 amd64
verified: 2026-09-25
commit: 2a2e0f5
status: 설계됨
scope: regtest · testnet
---
# ADR 색인
<MetadataCard versions="Project architecture" platforms="macOS arm64 · Windows WSL2 amd64" verified="2026-09-25" commit="2a2e0f5" status="설계됨" scope="regtest · testnet" />

| 결정 | 선택 | 핵심 이유 | 재검토 조건 |
| --- | --- | --- | --- |
| ADR-001 | 단일 노드 K3s | 두 로컬 OS에서 동일한 경량 배포 계약 | HA 또는 다중 운영자 요구 |
| ADR-002 | LND StatefulSet + PVC | 안정된 노드·storage identity | 외부 managed LND 상태 계층 |
| ADR-003 | regtest와 testnet 분리 | 파괴적 실습과 외부 상호운용 분리 | mainnet 운영 설계 시작 |
| ADR-004 | Prometheus/Grafana | metric·alert·dashboard를 Git으로 검증 | 장기 다중 클러스터 관측 |
| ADR-005 | Kyverno + Falco | admission과 runtime을 분리 | 관리형 정책·runtime 플랫폼 도입 |
| ADR-006 | 외부 Ollama + 제한 gateway | GPU 재사용과 권한 최소화 | 인증된 내부 inference 서비스 |
| ADR-007 | Vault 보안 확장 | 현재 수동 자금 경계를 유지 | 다중 사용자·비밀 회전 요구 |

