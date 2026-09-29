# 연재 근거 및 게시 전 확인 메모

이 파일은 글의 사실 관계를 관리하기 위한 편집용 기록이다. 게시 대상은 목차에 연결한 8편의 Markdown이며, 이 파일을 원본 운영 자료와 함께 공개할 필요는 없다.

## 재조회 범위

2026-09-29 저장소 코드·문서·로컬 Loop 성공 파일을 읽었다. Mac Kubernetes API와 WSL SSH 재접속은 실행 환경의 네트워크 권한으로 차단됐다. 확인 불가는 현재 클러스터 실패와 다르다. 글의 모든 live 결과는 2026-09-23~28 당시 결과로 한정한다.

| 사실 | 근거 | 판정과 사용 범위 |
|---|---|---|
| 현재 Phase 1~5 번호·제목 | `ops/start` PHASES | 소스에서 확인. 이전 acceptance 파일 번호는 의미로 대응 |
| Mac Lima/K3s 구성 | `docs/evidence/mac-stage1-2026-09-22.md` | 과거 기반 구축 기록. 최신 버전 안내로 사용하지 않음 |
| WSL regtest 양방향 10,000 sat | `docs/evidence/windows-regtest-mvp-2026-09-23.md` | 과거 실제 검증 문서. 외부 라우팅 증거 아님 |
| testnet 한 노드·30Gi·Neutrino | `charts/lnd-ops/values-testnet.yaml`, `templates/lnd.yaml` | 설정 확인. 현재 실행 설정과 동일하다고 단정하지 않음 |
| WSL 동기화·재배포 보존 | `docs/evidence/windows-testnet-phase1-2026-09-24.md` 및 실습 getinfo 출력 | 역사적 결과 |
| 방향별 잔액·anchor 오류 | 2026-09-27~28 사용자 명령 출력 | 서로 다른 스냅샷이며 총자산으로 합산하지 않음 |
| WSL 중계 1건·수수료 1.005 sat | 사용자 실시간 화면 출력 | 실습 경유 증거. 자연 유입·수익성·전체 Phase 완료는 미검증 |
| Mac Loop Out 성공 | `.cache/phase4-live-success.json`, checked_at 2026-09-28T03:19:31.670376+00:00 | 결과·금액·비용만 추출. 원본은 게시하지 않음 |
| Mac 비용 17,170 sat | 같은 파일의 server 11614 + onchain 5550 + offchain 6 | 합계 재계산. L402 별도 |
| WSL 세 번의 실패 | 이전 SSH 조회의 swaps·listpayments·Loop 로그 | TIMEOUT, NO_ROUTE, NO_ROUTE. 각각 swap 비용 0; L402·funding 별도 |
| 최소 Loop Out 250,000 sat | 당시 WSL `/v1/loop/out/terms` 조회 | 당시 서버 응답. 고정 프로토콜 기준 아님 |
| 세 번째 종료 135.27초·16 attempts | 당시 SSH 로그 및 swap 시각 차 | 종료 결과 확인, 외부 병목 위치는 미확정 |
| Mac 기존 monitoring release | 사용자 `helm list`·Pod/PVC 출력 | namespace lnd-monitoring, revision 5, 기존 배포 재사용 |
| 수집 네 작업 up=1 | 사용자 Prometheus 스크린샷 | scrape 성공만 증명. 모든 metric의 의미·정확성은 별도 |
| Rules·Alerts 오류 없음 | 사용자 UI 확인 응답 | 원본 규칙 export 부재. 현재 로컬 YAML과 완전 일치 주장 금지 |
| Phase 5 보류 기능 | 로컬 `ops/start` 및 `tests/test_start_phases.py` 변경 | 로컬 수정, remote/WSL 반영 미확인. 게시물에서 배포 완료로 주장하지 않음 |

## Phase 범위

Phase 1은 regtest, Phase 2는 지속 testnet, Phase 3은 Router 전환, Phase 4는 선택적 Loop, Phase 5는 관측 환경이다. 이전 observability Phase 3 기록을 현재 Router Phase 3 완료 증거로 전용하지 않는다. 최근 중계 실습 뒤에도 정책 미충족과 외부 접속 미검증이 화면에 남았다.

과거 보안·백업·장애·kagent 검증 문서가 존재하지만 이번 연재 범위에서는 자세히 다루지 않는다. 주문 진단용 kagent 튜닝과 OTel은 설계 대화 단계로, 배포 결과에 포함하지 않는다.

## 공개 및 재현 경계

게시물은 과거 실습의 1인칭 회고 초안이다. 작성 지원 도구의 조치와 사용자 수동 조작을 모두 직접 손으로 구현했다고 과장하지 않는다. 전체 결제 hash·preimage·노드 공개키·개인 호스트 주소·비밀번호·원본 private 증거를 복사하지 않았다.

조회 명령의 namespace/release 이름은 실습에 맞춘 예시다. 실제 환경에서 먼저 대상을 확인한다. 전체 Helm values/manifest와 Secret 출력은 공개 자료로 간주하지 않는다. 신규 결제·자금 이동·삭제·배포는 글 검증 과정에서 수행하지 않았다.

## 확장본 검토와 검증

8편 모두 연결된 자료의 핵심 설명을 본문에 풀었다. Helm 글을 2편으로 넣고 회차는 총 8편으로 맞췄으며, 기존 링크 보존을 위해 기존 파일명은 유지했다. 개념 예시의 숫자는 실측값과 구분하고, 최신 클러스터 결과로 서술하지 않았다.

- `sip`/`shower`: 별도 문맥의 검토자 세 명이 1~3편, 4~5편, 6~8편의 전체 복사본을 나눠 읽었다. 세 그룹 모두 독립적으로 읽히며 소폭 보완이 필요하다고 판정했다. kubeconfig 전제, 초기 peer 확보 절차, Mac·WSL의 별도 지갑, SCB 정의, 비용 예약 범위, HTLC 실제 경로 조회를 보충했다.
- `factchk`: Kubernetes 자원·Service·StatefulSet, Helm 입력과 출력, BOLT 채널·거래·그래프, LND v0.21.3-beta CLI 변환·복구 문서, Loop 및 Prometheus 공식 자료와 대조했다. 실제 lab 설정·수치는 로컬 template·collector·규칙·runbook·당시 실습 기록을 근거로 삼았다. 참조는 각 글에 남겼다.
- 코드 대조로 UI가 페이지를 순회한다는 초안 표현을 수정했다. 실제 구현은 최근 24시간에 최대 50,000건을 한 번 요청한다. `listchannels`의 숫자형 SCID와 64자리 channel ID 구분, 실패 결제 metric의 생성 시각 기준 한 시간 창도 본문에 명시했다.
- `ssotize`는 읽기 전용 일관성 감사로 적용했다. 차트 설정은 chart/template, 실시간 UI 동작은 `ops/router_forwarding.py`·`ops/start`, 비용 예약은 `ops/loop_ops.py`, 수집·규칙은 monitoring values·collector·rules를 기준으로 대조했다. source와 runbook 사이의 전체 통합이나 운영 설정 변경은 하지 않았다.
- `re0` 검토에서 기존 문단 사이에 설명을 연결하고 순서를 정리했다. 검증 한계를 유지하면서 링크를 열어야만 이해되는 문장을 줄였다. 새로운 평가 실험이나 이식성 주장을 만들지 않았으므로 `mandela`·`detool`은 적용하지 않았다.
- 전체 로컬 링크 33개, Bash·Zsh 명령 블록 22개, YAML 예시 3개, JSON 예시의 구문 검사를 통과했다. 중계 글 jq 예시 5개는 합성 응답에서 확인했다. 개인 식별자 전체 hex 노출 여부와 코드 fence도 검사했다.
- Helm lint와 testnet 기본·monitoring 활성화 로컬 렌더링을 통과했다. 이전 regtest·testnet 렌더링에서도 StatefulSet 개수와 단일 replica 구조를 확인했다. 이는 CLI 문서 검사이며 Linux 클러스터 실행 검증이 아니다.

검증 과정에서 클러스터 배포, 새 결제·swap·채널 종료, Git push 또는 블로그 게시는 수행하지 않았다. 현재 클러스터 상태는 앞서 적은 접근 제한으로 이번 편집에서 재확인하지 않았다.

## 장비 사양 반영 범위

1편에 Mac·WSL 실행 환경 표를 추가했다. Mac의 4 vCPU·8GiB·80GiB는 `ops/lima.yaml.in`의 현재 생성 설정이며 실제 VM 재조회 결과가 아니다. Windows OS·WSL·아키텍처는 기존 인프라 검증 기록으로 확인했다. `docs/windows-runbook.md`의 8 CPU·16GiB·여유 디스크 100GiB는 권장 조건으로만 설명했다.

물리 CPU 모델·전체 RAM과 WSL 실제 자원 할당은 저장소에 없고 호스트 조회도 권한 제한으로 실패해 사용자 확인을 요청했다.

별도 shower 검토자가 환경 표 전체를 읽어 설정·권장·실측 미확인 구분을 확인했다. 게스트 OS 행 이름을 설정·검증 기록으로 명확히 했다. 변경된 문서의 로컬 링크와 whitespace 검사를 통과했다. 하드웨어 확인 대기 항목을 검증 완료로 처리하지 않는다.

## 기존 Prometheus·Grafana 배포 설명 보강

7편에 현재 LND StatefulSet의 sidecar·ConfigMap·환경변수, 실제 scrape job의 endpoint 탐색·target label, Grafana의 데이터 소스 UID와 dashboard provisioning을 설명했다. 사용자 범위 수정에 따라 Loki는 추가하지 않았다. `cluster` label은 미적용 예시로 표시했다.

`factchk`로 로컬 template·collector·monitoring values 및 vendored chart 기본값을 대조했다. scrape YAML 예시는 실제 lndmon job과 객체 비교로 일치함을 확인했다. Kubernetes ConfigMap·Prometheus 설정·Grafana provisioning 공식 문서도 대조했다.

chart 기본 dashboard namespace 범위 ALL과 실제 release 미확인을 구분했다. `ssotize`는 설정 원본과 설명의 일관성 감사만 수행했다.

별도 shower 검토자가 추가 본문 전체를 읽었다. 현재 chart와 live 상태 구분을 도입에 보강하고, dashboard ConfigMap 조회 범위를 전체 namespace로 맞췄다. 문서 내 YAML 3개와 Bash·Zsh 명령 블록 5개, 로컬 링크 검사를 통과했다. 배포나 설정 변경은 수행하지 않았다.

7편에 초보자용 코드 흐름 설명을 추가했다. LND template·scrape relabel·실제 첫 대시보드 패널·ConfigMap label 명령을 발췌하고 설명했다. YAML·JSON·Bash 구문, 패널 필드·조회식 및 스크립트 명령의 원본 일치를 검사했다. 별도 shower 검토 후 실제 HTTP 수집 동작과 셸 변수의 의미를 보충했다. 실행 중인 환경에는 적용하지 않았다.

## 전체 연재의 쉬운 설명 개정

8편 모두 쉬운 개념 설명을 먼저 두고 실제 코드·조회 결과로 연결하도록 수정했다. 1편에는 저장 공간 연결 코드, 2편에는 values→template→YAML 예시, 6편에는 실제 Loop 실행 인자를 보충했다. 7편의 중복 수집 설명을 합치고 3편은 접속 대상·지갑 준비 뒤 조회하도록 순서를 바꿨다.

`edit-article`의 문단 길이 기준을 적용했다. `shower` 검토자 세 명이 8편 전체 복사본을 나눠 읽었고, Kubernetes Node와 Lightning 노드 구분, sat 단위, 인프라 용어, PromQL 문법, 브라우저 접속 주소를 보충했다. 실제 기록과 미확인 장비 사양의 경계는 유지했다.

검증 결과: 로컬 링크 36개, Bash·Zsh 명령 블록 24개, YAML 12개, JSON 2개 구문 검사 통과. 8편의 일반 문단은 각각 240자 이내다. Helm lint도 통과했다. 소스 코드·배포 설정·클러스터 상태는 변경하지 않았다.
