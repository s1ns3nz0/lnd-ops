---
title: 증거 기반 검증
description: 커밋, 플랫폼, 불변 조건을 비밀 없는 evidence로 연결한다
versions: Phase 8 · Phase 9
platforms: macOS arm64 · Windows WSL2 amd64
verified: 2026-09-25
commit: 2a2e0f5
status: 실제 환경 검증됨
scope: regtest · testnet
---
# 증거 기반 검증
<MetadataCard versions="Phase 8 · Phase 9" platforms="macOS arm64 · Windows WSL2 amd64" verified="2026-09-25" commit="2a2e0f5" status="실제 환경 검증됨" scope="regtest · testnet" />

“내 컴퓨터에서 됐다”는 말에는 어느 커밋인지, 새 환경이었는지, 이미 만든 지갑을 썼는지, 무엇을 확인했는지가 빠져 있다. 이 프로젝트의 evidence는 그 조건을 기록해 성공 주장을 다시 평가할 수 있게 만드는 자료다.

## 검증은 서로 다른 질문에 답한다

정적 검사는 잘못된 YAML, 끊어진 참조, 스크립트 문법을 찾는다. Helm 렌더링은 입력값이 Kubernetes 리소스로 변환되는지 확인한다. 실제 배포는 API와 storage, network가 맞물리는지 확인한다. 결제와 복구 실습은 그 위에서 LND의 업무 상태가 기대대로 바뀌는지 확인한다.

각 단계가 다음 단계를 대신하지 않는다. 이미지에 arm64 manifest가 있다고 Mac의 실제 wallet·channel 동작이 자동 검증되는 것은 아니다. 반대로 특정 Windows 환경의 결제 성공은 빈 환경 bootstrap의 누락을 찾지 못할 수 있다. 따라서 [Phase 8 교차 플랫폼 증거](https://github.com/s1ns3nz0/lnd-ops/blob/master/docs/evidence/phase8-cross-platform-2026-09-24.md)는 플랫폼과 시험 종류를 함께 읽어야 한다.

## 재배포에서 비교하는 이유

배포 뒤 pubkey만 확인하면 기존 채널이나 관측 이력을 잃은 문제를 놓칠 수 있다. PVC UID는 같은 storage 객체인지, channel 정보는 기존 채널을 유지했는지, SCB는 복구 자료의 연속성을, 과거 Prometheus sample은 관측 이력을 보여준다. 서로 다른 손실을 찾기 위해 여러 조건을 사용한다.

이 비교를 [`ops/redeploy-check`](https://github.com/s1ns3nz0/lnd-ops/blob/master/ops/redeploy-check)에 구현했다. 이 스크립트는 실제로 배포를 수행하므로 읽기 전용 학습 명령처럼 실행하면 안 된다. 코드를 읽을 때는 preflight, 상태 캡처, chart 적용, 결과 비교의 순서를 따라간다.

## 근거 파일을 해석하는 방법

커밋은 그때 사용한 구현을 식별한다. 날짜는 증거의 시점을 보여준다. 결과가 pass여도 현재 클러스터가 계속 같은 상태라는 뜻은 아니다. 이후 설정 변경, 지갑 잠금, peer 이탈이 발생하면 과거 증거와 현재 관측을 구분해야 한다.

Wiki 상단의 `실제 환경 검증됨`은 연결된 기존 구현의 검증 기록을 뜻한다. 문장을 추가했다고 새 장애 실험을 수행한 것은 아니므로 원래 날짜와 커밋을 유지한다. 자동 검사는 문서 구조를 검증하지만 서술 전체의 기술적 진실을 보증하지 않는다.

## 증거에 원시 로그를 모두 넣지 않는 이유

운영 로그에는 식별자와 자격 증명, 결제 정보가 섞일 수 있다. retained evidence는 필요한 boolean 결과와 실행 조건을 기록하고, 민감한 응답은 공개 페이지에 복사하지 않는다. 다만 boolean만 보면 무엇을 시험했는지 이해하기 어렵다. 그래서 공개 설명에서 수행 시나리오와 불변 조건, 한계를 함께 연결한다.

예를 들어 [Phase 7 증거](https://github.com/s1ns3nz0/lnd-ops/blob/master/docs/evidence/windows-phase7-kagent-2026-09-24.md)는 진단 응답과 제한된 gateway 동작을, [Phase 6 증거](https://github.com/s1ns3nz0/lnd-ops/blob/master/docs/evidence/windows-phase6-faults-2026-09-24.md)는 alert 전달과 원복을 설명한다. 이 둘을 합쳐도 모든 LND 장애를 LLM이 자동 수리했다고 결론내릴 수는 없다.

## 읽기 전용 연습

```sh
git rev-parse HEAD
ops/demo --list --no-color
ops/demo --to 7 --dry-run --no-color
```

현재 커밋과 실행 계획을 읽고, 각 단계가 새 실험을 하는지 기존 증거를 검사하는지 구분한다. 전체 데모의 단계별 계약은 [Phase 9 runbook](https://github.com/s1ns3nz0/lnd-ops/blob/master/docs/phase9-demo-runbook.md)에 있다.

<details class="quiz"><summary>면접 질문: 녹색 CI가 있어도 운영 준비 완료를 말할 수 없는 경우는?</summary>CI가 문법·렌더링만 검증했거나, 실험의 플랫폼·네트워크·데이터 조건이 운영 환경과 다를 때다. 성공한 검사 이름보다 그 검사가 배제한 실패가 무엇인지 설명해야 한다.</details>

다음 [설계 회고](/12-retrospective/tradeoffs)에서는 증명한 범위를 토대로 확장 순서를 정한다.
