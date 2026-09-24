---
title: 장애 대응 수명주기
description: 증상, 근거, 조치, 복구 검증을 버전이 붙은 runbook으로 연결한다
versions: Prometheus · Alertmanager · Kubernetes 1.36
platforms: macOS arm64 · Windows WSL2 amd64
verified: 2026-09-24
commit: 841692b
status: 실제 환경 검증됨
scope: regtest · testnet
---
# 장애 대응 수명주기
채널 비활성 경보를 받았다고 즉시 LND를 재시작하면 잠긴 wallet이라는 문제가 추가될 수 있다. 같은 증상은 peer 종료, 네트워크 차단, 체인 상태, 의도된 정비에서 모두 나타난다. runbook은 이러한 여러 가능성 사이에서 다음 확인 대상을 고르는 절차다.

## 아주 쉽게 비유하면: 불이 안 켜질 때 순서대로 살펴보기

장난감 불이 안 켜지면 바로 새 장난감을 사기 전에 스위치가 켜졌는지, 건전지가 들어 있는지, 전선이 빠졌는지 본다. 건전지를 갈았다면 마지막에 정말 불이 켜지는지도 확인한다.

**실제 시스템에 연결하면:** Runbook은 증상에서 원인을 좁히고 조치 후 회복을 확인하는 순서다. 실제 노드는 여러 원인이 겹칠 수 있어 한 번의 관측으로 확정하지 않는다. 재시작 같은 변경 전에 읽기 전용 관측으로 후보를 줄이는 이유다.

## 배경: 증상에서 원인으로 좁혀 가는 방법

Runbook은 명령어 모음에 앞서 판단 순서를 기록한 문서다. 좋은 첫 단계는 상태를 많이 바꾸는 조치가 아니라 원인 후보를 나누는 관측이다. 예를 들어 “채널 inactive”의 원인은 로컬 LND 중단, peer 단절, 네트워크 정책, 원격 노드 상태 등 여러 가지일 수 있다. 같은 증상에 같은 재시작을 반복하면 원인과 관계없는 조치를 할 가능성이 커진다.

먼저 로컬 RPC 응답과 wallet 상태를 확인하면 프로세스·지갑 문제와 peer 문제를 나눌 수 있다. 그다음 peer와 채널 상태를 비교하고, 변경 이력과 NetworkPolicy를 확인하면 통신 경로 가설을 좁힐 수 있다. 각 단계는 “이 결과가 참이면 무엇을 제외하고 다음에 무엇을 볼 것인가”를 설명해야 한다. 증거가 부족하면 원인 미확정으로 남기는 것도 올바른 진단 결과다.

예를 들어 장애 직전에 정책 변경이 있었다는 사실은 유력한 단서지만 단독으로 인과관계를 증명하지 않는다. 원래 정책 복원 뒤 peer와 채널이 회복되는지 확인하면 가설을 더 강하게 지지할 수 있다. 이때 함께 일어난 다른 변경이 있다면 기록해야 한다. 실습에서 한 번에 하나의 fault를 넣는 것은 이런 해석을 쉽게 하기 위해서다.

## 배경: 복구 명령의 성공과 서비스 회복의 차이

Kubernetes API가 patch 요청을 받아들여도 컨트롤러의 실제 반영은 뒤따라 일어난다. 프로세스가 시작된 뒤에도 wallet unlock과 동기화, peer 재연결이 남을 수 있다. 따라서 대응에는 “명령 실행됨”과 “원래 사용자 행동이 다시 가능함”을 각각 확인하는 단계가 있어야 한다.

재시도도 조건이 필요하다. 읽기 요청의 일시 실패와 지급처럼 외부 효과를 만드는 요청의 실패는 다르게 취급해야 한다. 특히 응답을 받지 못했다는 사실은 상대가 요청을 실행하지 않았다는 증거가 아니다. 무조건 다시 실행하기 전에 기존 작업의 상태를 확인할 수 있어야 한다.

이 프로젝트의 자동 조치는 이러한 위험을 작게 제한해 진단용 probe 재시작만 다룬다. 실제 LND 재시작을 자동화하려면 지갑 잠금, 진행 중인 작업, 복구 후 검증, 반복 실행 제한까지 포함하는 별도의 계약이 필요하다. 아래의 실습 순서는 현재 구현된 경계를 기준으로 읽는다.


## 경보가 원인을 말해주지는 않는다

`LndOpsChannelInactive`는 inactive 채널이 있다는 신호가 일정 시간 유지됐다는 뜻이다. 어느 네트워크 장비가 패킷을 버렸는지까지 증명하지 않는다. 따라서 첫 단계는 경보의 namespace와 workload를 확인하고, wallet과 exporter가 상태를 제대로 보고하는지 확인하는 것이다.

다음으로 peer 연결과 최근 변경을 본다. 직전에 NetworkPolicy를 바꿨다면 연결 장애의 유력한 단서지만, 변경 시점만으로 원인을 확정하지 않는다. 실제 적용된 정책, 대상 Pod, Event와 로그를 연결한다. [`channel-inactive` runbook](https://github.com/s1ns3nz0/lnd-ops/blob/master/docs/runbooks/channel-inactive.md)은 읽기, 가설, 수동 조치와 종료 기준을 한 흐름으로 묶는다.

## 사례: peer 정책 변경 뒤 채널이 inactive가 됨

학습용 시나리오에서 wallet과 chain sync는 정상인데 channel만 inactive로 변했다고 가정하자. 이 경우 지갑 복구보다 peer 통신을 먼저 확인할 근거가 있다. 최근 정책 변경과 일치한다면 원래 정책을 복원하는 것이 작은 조치다. channel force close는 연결 문제에 비해 훨씬 큰 영속 상태 변경이다.

정책을 복원한 뒤에도 incident는 끝나지 않는다. API가 patch를 수락했는지, peer가 재연결됐는지, 채널이 active로 돌아왔는지, exporter가 새 값을 수집했는지 순서대로 확인한다. alert가 사라졌더라도 scrape가 끊겨 시계열이 없어졌다면 서비스 회복으로 해석하면 안 된다.

## 장애 주입으로 무엇을 시험했는가

[`ops/exercise-phase6-faults`](https://github.com/s1ns3nz0/lnd-ops/blob/master/ops/exercise-phase6-faults)는 regtest 채널 격리, 일회성 CrashLoop Pod, Falco marker를 사용한다. metric이나 event가 생기는 것뿐 아니라 실제 경보 지속 시간, Alertmanager 전달, runbook 연결, 원복 후 상태까지 확인하는 시험이다.

Falco marker 성공은 해당 탐지·전달 경로가 작동한다는 증거다. 가능한 모든 침해를 탐지했다는 증거는 아니다. 마찬가지로 regtest의 정책 차단 실습은 테스트넷 peer의 장기 장애나 모든 네트워크 실패를 대표하지 않는다. [공개 Phase 6 증거](https://github.com/s1ns3nz0/lnd-ops/blob/master/docs/evidence/windows-phase6-faults-2026-09-24.md)는 시험 범위를 확인할 때 사용한다.

## 실행 취소와 원복을 미리 설계하는 이유

장애를 넣는 코드보다 원래 상태를 기억하는 코드가 먼저 필요하다. 정책을 “허용으로 바꾸기”만 하면 사고 전 정책의 좁은 범위가 사라질 수 있다. 원본을 저장하고 정확히 되돌리는 것과, 일반적인 기본 정책을 재적용하는 것은 다르다.

`finally`는 정상 예외나 처리 가능한 중단에서 원복을 돕지만 전원 단절까지 보장하지 않는다. 그래서 별도의 정리 절차와 사후 검증이 필요하다. [`ops/demo cleanup`](https://github.com/s1ns3nz0/lnd-ops/blob/master/ops/demo-cleanup)은 정해진 잔여물만 대상으로 하며, 이를 지갑 복구나 전체 환경 초기화에 대신 사용하지 않는다.

## 변경 없이 대응 흐름 읽기

```sh
kubectl -n lnd-regtest get networkpolicy
kubectl -n lnd-regtest get events --sort-by=.lastTimestamp
ops/demo --to 7 --dry-run --no-color
```

이 출력으로 정책 이름, 최근 Event, 데모가 변경하는 단계와 검증하는 단계를 구분한다. 실제 fault 실행은 선행 조건과 원복 절차가 있는 [데모 runbook](https://github.com/s1ns3nz0/lnd-ops/blob/master/docs/phase9-demo-runbook.md)에서 수행한다.

<details class="quiz"><summary>면접 질문: alert가 cleared인데 incident를 닫지 않을 이유는?</summary>telemetry가 사라졌거나 rule이 삭제됐을 수도 있다. 업무 신호가 정상으로 돌아왔고 관측도 계속 정상이라는 두 조건을 확인해야 한다.</details>

다음 [심층 방어](/09-security/defense-in-depth)는 장애 대응 이전에 잘못된 변경과 불필요한 접근을 줄이는 통제를 설명한다.

## 이 설계가 정해진 과정

[데모와 잔여 자원 정리까지 자동화한 이유](/decisions/#adr-012). 대화에서 정한 방향과 현재 구현·보류 범위를 함께 읽는다.
