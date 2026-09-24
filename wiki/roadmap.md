---
title: 학습 지도
description: LND 운영 생명주기를 따라가는 12단계 학습 경로
versions: K3s 1.36.4 · Helm 4.1.4 · kagent 0.9.12
platforms: macOS arm64 · Windows WSL2 amd64
verified: 2026-09-25
commit: 2a2e0f5
status: 자동 검증됨
scope: regtest · testnet
---

# 학습 지도

<MetadataCard versions="K3s 1.36.4 · Helm 4.1.4 · kagent 0.9.12" platforms="macOS arm64 · Windows WSL2 amd64" verified="2026-09-25" commit="2a2e0f5" status="자동 검증됨" scope="regtest · testnet" />

기술 이름을 외우는 대신 노드의 생명주기를 따라간다. 앞 단계의 요구가 다음 단계의 설계 입력이 된다.

```text
LND 상태 이해 → 요구사항 → Kubernetes → Helm → 지갑 → 채널과 결제
      → 관측 → 장애 대응 → 보안과 복구 → kagent → 검증 → 회고
```

| 단계 | 답해야 할 질문 | 완료 기준 |
| --- | --- | --- |
| 1 | LND가 어떤 상태를 만들고 어떤 프로토콜과 통신하는가? | wallet, channel.db, macaroon, TLS, SCB 역할을 구분한다 |
| 2 | 그 상태 때문에 플랫폼에 무엇이 필요한가? | 영속성·신원·네트워크·복구 요구를 적는다 |
| 3 | 왜 StatefulSet과 PVC인가? | Pod 교체와 노드 신원 보존을 연결한다 |
| 4 | 왜 Helm과 멱등 스크립트인가? | 빈 환경과 재배포 계약을 설명한다 |
| 5 | 어떤 비밀을 어디까지 자동화할 수 있는가? | seed, password, macaroon, SCB 경계를 구분한다 |
| 6 | 용량과 유동성은 왜 다른가? | send/receive 가능성을 별도 판단한다 |
| 7 | 왜 그 메트릭과 임계값인가? | 사용자 영향과 신호를 연결한다 |
| 8 | runbook은 어떻게 모호성을 줄이는가? | 증상→근거→조치→검증 흐름을 만든다 |
| 9 | 예방·탐지·복구가 어떻게 겹치는가? | Kyverno, NetworkPolicy, RBAC, Falco, SCB 역할을 구분한다 |
| 10 | LLM에게 어떤 권한을 주어야 하는가? | 현재/승인 필요/향후 기능을 나눈다 |
| 11 | 무엇을 통과해야 완료인가? | 커밋·플랫폼·증거가 연결된 acceptance를 설명한다 |
| 12 | 현재 설계가 어디서 깨지는가? | 단일 노드와 홈 네트워크의 한계를 말한다 |

## 추천 경로

1. [LND 구조와 상태](/01-foundations/lnd-architecture)
2. [StatefulSet과 PVC](/03-kubernetes/stateful-design)
3. [채널·유동성·결제](/06-payments/channel-liquidity)
4. [신호에서 판단까지](/07-observability/signals-to-decisions)
5. [Observe에서 Verify까지](/10-automation/observe-to-act)

