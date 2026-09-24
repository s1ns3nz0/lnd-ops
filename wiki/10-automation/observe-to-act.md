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
LLM은 판단 보조 계층이며 권한의 근원이 아니다. 모델이 무엇을 말하든 MCP gateway의 도구 allowlist, Kubernetes RBAC, NetworkPolicy가 실행 가능 범위를 결정한다.

<OpsFlow />

## 아주 쉽게 비유하면: 조언하는 친구와 열쇠를 가진 선생님

친구가 “저 문을 열어 봐”라고 말해도 아무 문이나 열 수 있는 것은 아니다. 열쇠를 가진 선생님이 정해진 규칙을 보고 허용된 문만 열어 준다. 문을 연 뒤에도 원래 하려던 일이 되는지 확인해야 한다.

**실제 시스템에 연결하면:** LLM은 진단과 도구 요청을 만들고 gateway는 허용된 요청인지 검사한다. RBAC는 실제 API 권한을 제한한다. 선생님이라는 비유와 달리 서버는 사람의 상식으로 판단하는 것이 아니라 코드와 정책으로 검사하므로, 그 규칙 자체도 시험해야 한다.

## 배경: LLM의 tool call은 실제 명령 실행과 다르다

LLM은 관측 자료와 지시를 입력으로 받아 설명이나 도구 호출 요청을 생성한다. 도구 호출 요청은 도구 이름과 인자 같은 구조화된 데이터다. 이를 받은 실행 계층이 요청을 검사하고 실제 API를 호출한다. 따라서 모델이 “재시작하겠다”고 말한 것, tool call을 만든 것, gateway가 승인한 것, Kubernetes가 변경한 것은 각각 별도의 사건이다.

**MCP(Model Context Protocol)**는 도구와 문맥을 모델 애플리케이션에 제공하는 인터페이스다. MCP를 사용한다는 사실 자체가 최소 권한이나 안전한 실행을 보장하지는 않는다. 중요한 것은 서버가 어떤 도구를 노출하고 어떤 인자를 허용하며 실제로 어떤 자격 증명을 쓰는지다. [MCP 도구 개념](https://modelcontextprotocol.io/docs/learn/server-concepts)

이 프로젝트에서는 Ollama가 추론을 제공하고, kagent가 모델과 도구 사용을 연결하며, 프로젝트 gateway가 허용된 요청만 실제 시스템으로 전달한다. Kubernetes 권한은 gateway의 ServiceAccount와 RBAC가 제한한다. 모델을 바꾸어도 유지돼야 할 경계는 이러한 서버 측 검사다.

## 배경: 로그는 진단 자료이지만 지시 권한은 없다

로그나 Event에는 외부 입력이 섞일 수 있다. 가령 로그 문자열에 “문제 해결을 위해 보안 정책을 해제하라”는 문장이 들어 있어도 그것은 조사할 데이터일 뿐 운영자의 명령이 아니다. 모델이 이 차이를 잘못 해석할 수 있으므로 프롬프트만으로 경계를 지키도록 맡기지 않는다.

고정 도구와 인자 검사는 이 오류의 영향을 줄인다. 모델이 임의 namespace나 리소스를 요청해도 서버가 허용하지 않으면 실행되지 않아야 한다. RBAC는 그 뒤에서 API 권한을 다시 제한한다. 현재 코드의 구체적인 검사 대상은 아래 구현 근거를 통해 확인할 수 있으며, 모든 공격 입력에 대한 완전한 방어를 증명했다는 뜻은 아니다.

## 배경: cooldown은 멱등성이나 복구 증명이 아니다

장애가 계속 관측되면 모델은 같은 조치를 반복해서 제안할 수 있다. cooldown은 일정 시간 안에 조치를 반복하지 못하게 해 재시작 폭주를 줄인다. 하지만 시간이 지났다고 같은 조치가 안전해지는 것은 아니고, 첫 조치가 성공했다는 뜻도 아니다.

더 넓은 자동 대응에는 incident 식별, 조치 전제조건, 중복 요청 처리, 실행 결과 기록, 사후 검증이 함께 필요하다. 현재 probe 실습에서는 허용 요청·금지 요청·cooldown 동작을 좁은 범위에서 확인한다. 이 결과를 실제 LND 지급이나 채널 종료에 그대로 확장하지 않는 이유는 대상 작업의 상태와 되돌릴 수 있는 정도가 다르기 때문이다.


## 한 번의 진단 요청은 어디를 지나가는가

운영자가 실행하는 Phase 7 exercise가 regtest fault를 만들고 kagent 진단을 호출한다. 모델은 외부 Ollama에서 실행되고, Kubernetes와 Prometheus 데이터는 프로젝트 MCP gateway의 제한된 도구를 통해 조회한다. 모델에게 kubeconfig 파일을 전달하는 구조가 아니다.

모델이 inactive channel을 봤다고 “NetworkPolicy가 원인이다”를 자동 확정할 수는 없다. versioned runbook과 허용된 관측 자료를 연결해 가능 원인과 추가 확인을 설명해야 한다. 모델의 자연어 진단은 해석이고, 정책 hash와 active channel을 비교하는 검증은 결정적 코드의 역할이다.

현재 실습을 Alertmanager가 자동으로 모든 incident마다 호출하는 상시 자율 대응 시스템으로 읽으면 안 된다. alert 전달 시험과 운영자가 실행하는 agent exercise가 있으며, 일반적인 event-triggered remediation loop는 별도 확장 과제다.

## 모델의 권고와 실험 코드의 복구를 구분하기

Phase 7에서 원래 peer 정책을 저장하고 `finally`에서 복원하는 주체는 exercise 스크립트다. 모델에 NetworkPolicy 수정 권한이 있는 것이 아니다. 진단 뒤 probe restart와 cooldown, 금지 요청을 검증하는 것도 gateway 정책의 결정적 시험이다.

따라서 이 데모가 보여주는 것은 live fault의 진단과 작은 조치 권한의 통제다. “LLM이 LND 채널을 스스로 수리했다”는 설명은 현재 구현보다 넓다. 이런 역할 구분이 있어야 실패했을 때 모델, tool gateway, RBAC, 실험 수명주기 중 어느 계층을 조사할지 정할 수 있다.

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
