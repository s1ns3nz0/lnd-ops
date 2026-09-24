---
title: LND Ops Wiki
description: LND 운영 요구를 Kubernetes 설계와 연결하는 학습 Wiki
versions: LND pinned image · K3s 1.36.4 · Helm 4.1.4
platforms: macOS arm64 · Windows WSL2 amd64
verified: 2026-09-25
commit: 2a2e0f5
status: 실제 환경 검증됨
scope: regtest · testnet
layout: home
hero:
  name: LND Ops Wiki
  text: Lightning 노드를 운영 가능한 플랫폼으로 번역하기
  tagline: LND의 사용 사례와 첫 결제 흐름에서 출발해 Kubernetes, 관측, 보안, runbook, kagent 설계의 이유를 추적합니다.
  image:
    src: /banner.png
    alt: LND Ops 색상 배너
  actions:
    - theme: brand
      text: 학습 시작
      link: /start-here
    - theme: alt
      text: 저장소 보기
      link: https://github.com/s1ns3nz0/lnd-ops
features:
  - title: 원리에서 구현까지
    details: 공식 자료의 원리, 프로젝트 판단, 실제 Helm·스크립트 구현을 분리해서 연결합니다.
  - title: 신호에서 대응까지
    details: 왜 그 지표를 보는지, 어떤 alert와 runbook을 거쳐 어떻게 안전하게 조치하는지 설명합니다.
  - title: 검증 가능한 포트폴리오
    details: macOS arm64와 Windows WSL2 amd64에서 수행한 증거와 현재 한계를 함께 기록합니다.
---

## 이 Wiki를 읽는 법

먼저 **사용 사례 → 노드 준비 → 채널 개설 → 송수신과 정산**을 따라갑니다. 그다음 내부 구조를 이해하고 **운영 요구 → 플랫폼 설계 → 관측 → 보안 → 대응 → 검증**으로 이어갑니다. Linux와 Kubernetes 기본 사용 경험은 가정하지만 LND의 개념은 처음부터 설명합니다. 장 후반의 선택 비교와 면접 질문은 플랫폼 엔지니어 수준의 검토를 목표로 합니다.

::: tip 사실의 종류
`공식 원리`는 외부 1차 자료, `프로젝트 판단`은 이 저장소의 선택, `구현 근거`는 코드, `검증`은 테스트와 실행 증거, `제약`은 아직 증명하지 못한 범위를 뜻합니다.
:::

## 어디서 시작할까

- 처음 실행한다면 [안전하게 시작하기](/start-here)
- LND가 처음이라면 [사용 사례와 전체 흐름](/01-foundations/lnd-workflow)
- 전체 순서를 보려면 [학습 지도](/roadmap)
- 상태 보존이 궁금하면 [LND 구조와 상태](/01-foundations/lnd-architecture)
- 운영 자동화가 궁금하면 [신호에서 판단까지](/07-observability/signals-to-decisions)
