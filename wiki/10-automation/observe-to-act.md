---
title: Observe에서 Verify까지
description: kagent와 Ollama가 runbook을 사용하되 권한 경계를 넘지 않는 자동 대응 구조
versions: kagent 0.9.12 · Ollama gpt-oss:20b tested
platforms: Windows WSL2 amd64 + macOS Ollama
verified: 2026-09-24
commit: 841692b
status: 실제 환경 검증됨
scope: regtest
---
# Observe에서 Verify까지
<MetadataCard versions="kagent 0.9.12 · Ollama gpt-oss:20b tested" platforms="Windows WSL2 amd64 + macOS Ollama" verified="2026-09-24" commit="841692b" status="실제 환경 검증됨" scope="regtest" />

LLM은 판단 보조 계층이며 권한의 근원이 아니다. 모델이 무엇을 말하든 MCP gateway의 도구 allowlist, Kubernetes RBAC, NetworkPolicy가 실행 가능 범위를 결정한다.

<OpsFlow />

## 현재 검증된 기능

- allowlist에 포함된 Pod, StatefulSet, PVC, Event 조회
- 마지막 50줄의 redacted log 조회
- inactive channel, unready Pod, Falco event용 고정 PromQL 진단
- 커밋에 포함된 세 개의 versioned runbook 조회
- health verification
- 진단용 probe Deployment 재시작 1개
- 5분 cooldown, 허용·거부 Kubernetes Event 감사
- `unlock_wallet` 요청의 gateway·RBAC 거부

## 운영자 승인이 필요한 기능

wallet unlock, seed 사용, payment, channel open/close, LND restart, PVC·SCB 삭제, NetworkPolicy 완화는 모델의 직접 실행 범위가 아니다. 제안은 가능하지만 운영자가 상태와 영향 범위를 검토해야 한다.

현재 구현에는 이러한 고위험 조치를 실행하는 **승인 토큰이나 승인 API가 없다**. 운영자는 모델 응답 밖에서 해당 버전의 runbook을 읽고 명령을 직접 수행한다. 따라서 “운영자 승인 필요”는 자동 실행이 대기 중이라는 뜻이 아니라, gateway가 그 기능을 제공하지 않는다는 뜻이다. 향후 승인 흐름을 추가하려면 action preview, 단일 사용 승인, 만료, approver identity, audit record, rollback과 사후 verification을 먼저 정의해야 한다.

## 향후 설계

- 더 많은 versioned runbook과 고정 진단 쿼리
- 여러 alert와 Event의 시간 상관분석
- dry-run 가능한 remediation plan
- 승인 토큰의 수명과 단일 사용 감사
- 외부 가용성 신호와 내부 원인의 상관관계

## 왜 일반 kubectl 도구를 주지 않았나

자연어 의도 분류의 실수는 피할 수 없다. 따라서 “위험한 명령을 프롬프트로 금지”하는 대신 서버가 여섯 개 도구와 고정된 파라미터만 제공한다. gateway ServiceAccount만 제한된 token을 가지며 kagent Agent는 token-free다.

| 요구사항 | 선택 | 대안 | 선택 이유 | 비용·한계 |
| --- | --- | --- | --- | --- |
| 진단 유연성 | LLM + 고정 관측 도구 | shell/kubectl 전체 제공 | 데이터 해석은 유연, 권한은 결정적 | 새 시나리오마다 도구 추가 필요 |
| 모델 운영 | Mac 외부 Ollama | cluster 내부 GPU 모델 | 현재 하드웨어 재사용 | LAN·가용성·TLS 경계 추가 |
| 변경 통제 | probe restart 1개 | 모든 runbook 자동화 | end-to-end mutation을 안전하게 증명 | 실제 LND 자동 복구는 하지 않음 |
| 감사 | Kubernetes Event + private evidence | 대화 로그만 저장 | 실행·거부를 정책 계층에서 기록 | Event는 단기 보존 |

## 실제 장애 흐름

Phase 7은 regtest peer NetworkPolicy를 임시 차단해 inactive channel 신호를 만든다. kagent는 live metric과 channel runbook을 사용해 진단한다. `finally` 경로가 원래 정책을 복원하고 channel active를 확인한 후에만 allowlisted probe 조치를 검증한다.

## 구현 근거

- [`agent/runbook_gateway.py`](https://github.com/s1ns3nz0/lnd-ops/blob/master/agent/runbook_gateway.py): 도구 입력 검증, redaction, cooldown, event
- [`charts/agent/templates/cross-namespace-rbac.yaml`](https://github.com/s1ns3nz0/lnd-ops/blob/master/charts/agent/templates/cross-namespace-rbac.yaml): namespace별 읽기 권한
- [`charts/agent/templates/resources.yaml`](https://github.com/s1ns3nz0/lnd-ops/blob/master/charts/agent/templates/resources.yaml): token, network, mutation 경계
- [`docs/phase7-runbook.md`](https://github.com/s1ns3nz0/lnd-ops/blob/master/docs/phase7-runbook.md): 배포와 acceptance

## 점검 문제
<details class="quiz"><summary>프롬프트에 “지갑 작업 금지”라고 쓰는 것만으로 부족한 이유는?</summary>프롬프트는 권한 통제가 아니며 오해·주입·모델 오류가 가능하다. 서버 allowlist와 RBAC가 요청을 결정적으로 거부해야 한다.</details>
<details class="quiz"><summary>왜 Act 뒤에 Verify가 독립 단계인가?</summary>API 호출 성공은 사용자 영향 회복을 뜻하지 않는다. 정책 원복, workload 상태, channel·metric 회복을 별도로 확인해야 한다.</details>

### 면접 질문
> 자동 remediation 범위를 넓힐 때 위험도를 어떤 기준으로 분류하고, 승인과 rollback을 어떤 상태 머신으로 표현할 것인가?
