---
title: 한계와 다음 단계
description: 현재 로컬 단일 노드 설계가 증명한 것과 증명하지 않은 것을 구분한다
versions: K3s 1.36.4 · project MVP
platforms: macOS arm64 · Windows WSL2 amd64
verified: 2026-09-25
commit: 2a2e0f5
status: 실제 환경 검증됨
scope: regtest · testnet
---
# 한계와 다음 단계
<MetadataCard versions="K3s 1.36.4 · project MVP" platforms="macOS arm64 · Windows WSL2 amd64" verified="2026-09-25" commit="2a2e0f5" status="실제 환경 검증됨" scope="regtest · testnet" />

이 프로젝트의 가치는 도구 수보다 선택한 운영 계약을 두 플랫폼에서 재현하고 실패를 설명할 수 있다는 데 있다. 동시에 단일 사용자 홈 환경에서 합리적인 선택이 여러 운영자와 실제 서비스에서도 충분한지는 별도 질문이다. 이 장에서는 기존 설계가 어느 조건에서 재검토되어야 하는지 살펴본다.

## Kubernetes가 현재 해결한 문제

같은 Helm chart로 workload, storage 연결, network 경계를 선언하고 monitoring·security·agent를 반복 배포할 수 있게 했다. 이는 도구마다 수동 설치 순서를 기억하던 부담을 줄인다. 하지만 Kubernetes controller가 Bitcoin과 Lightning의 자금 상태를 이해하는 것은 아니다. wallet unlock과 SCB 복구 판단은 여전히 애플리케이션 운영 영역이다.

한 대의 머신에 LND만 띄우는 목표라면 Docker Compose나 systemd가 더 작은 운영 비용을 가질 수 있다. 여기서는 정책과 관측, 자동 대응, 여러 플랫폼의 배포 계약을 함께 학습하고 검증하려고 Kubernetes 비용을 받아들였다. 이 목적을 빼고 “LND에는 Kubernetes가 필수”라고 주장하지 않는다.

## 다중 노드로 바꿀 때 먼저 풀 문제

노드 수를 늘리기 전에 wallet 데이터가 어디에 있으며 누가 쓰는지 정해야 한다. local-path 데이터가 원래 노드에 남으면 다른 노드에 Pod를 예약해도 상태가 따라오지 않는다. 반대로 공유 storage를 붙였다고 같은 identity의 두 프로세스가 동시에 동작해도 안전해지지 않는다.

재검토할 것은 storage 가용성, 단일 writer 보장, 기존 노드가 정지됐음을 확인하는 fencing, 복구 입력과 시간이다. replicas를 늘리는 작업과 동일 LND의 안전한 failover 설계는 다르다. 이 Wiki의 현재 evidence에는 다중 노드 HA 검증이 없다.

## 관측의 바깥을 관측해야 한다

PC가 꺼지면 그 안의 Prometheus와 Alertmanager도 멈춘다. 내부 metric을 더 늘려도 이 상태에서 알림을 전송할 수 없다. 실제 서비스 가용성을 요구한다면 독립된 외부 관측 지점과 연락 경로가 필요하다. 보관 기간이 긴 로그와 감사 기록 역시 cluster 밖 보관을 검토할 이유가 된다.

현재 결제 관측에는 receive-failure의 의미를 정의하고 수집하는 공백이 있다. 취소된 invoice를 실패로 세면 사용하지 않은 invoice까지 장애처럼 보일 수 있다. 따라서 먼저 사용자 관점의 실패를 정의하고, 그 결과를 뒷받침할 데이터가 있는지 확인하는 순서가 맞다.

## 보안 확장의 우선순위

현재 남은 제약에는 Windows 전체 볼륨 암호화 유예와 같은 PC에 놓인 백업, LND Pod의 일부 root 실행, sidecar의 넓은 read-only 파일 접근이 있다. Vault 같은 새 도구를 추가하는 판단은 이 중 어느 위협을 해결하는지에 연결해야 한다.

예를 들어 디스크 분실이 우선 위협이면 host 암호화와 독립 백업의 의미가 크다. 다중 운영자가 자격 증명을 회전해야 한다면 Vault의 효용이 커진다. 두 문제를 같은 “보안 강화” 항목으로 묶으면 무엇을 완료했는지 평가하기 어렵다.

## 자동 대응을 넓히는 조건

현재 probe 재시작은 변경 권한과 cooldown, audit를 증명하는 작은 실험이다. 이를 실제 LND 재시작으로 넓히면 wallet 잠금과 진행 중인 작업의 영향이 생긴다. 조치 전제, 금지 조건, 성공 기준, rollback 가능 여부를 runbook에 쓰고 결정적 검사로 표현할 수 있을 때 다음 후보가 된다.

[기술 선택 기록](/decisions/)은 이런 재검토 조건을 남기는 곳이다. 새로운 도구를 선택할 때는 “기존 실패 모델에서 무엇이 바뀌었는가”부터 적는다.

<details class="quiz"><summary>면접 질문: 다음 한 달의 과업을 하나 고른다면 어떤 근거를 제시할까?</summary>요구가 외부 서비스 가용성이라면 외부 감시, 데이터 상실 대응이라면 독립 백업과 복구 재검증, 다중 운영자라면 권한·감사 체계를 우선할 수 있다. 유행하는 도구보다 가장 큰 미해결 실패와 연결된 선택이어야 한다.</details>
