# Kubernetes에서 Lightning 노드 운영하기: Phase 1~5 실습 회고

LND를 처음 공부하는 독자가 따라 읽을 수 있도록 쓴 실습 연재다. 쉬운 설명 뒤에 실제 저장소 코드나 조회 명령을 놓고, 각 줄의 역할과 결과를 읽는 방법을 설명한다.

각 글에서는 개념 예시, 실제 코드 발췌, 당시 실습 결과를 구분한다. 코드 발췌는 완전한 설치 파일이 아니며, 따로 표시한 조회 명령은 현재 대상 클러스터를 확인한 뒤 읽는 용도로 쓴다. 새 결제나 배포를 실행하는 실습 지침으로 읽지 않는다.

| 편 | 제목 | 현재 lab Phase |
|---|---|---|
| 1 | [지갑이 있는 프로그램을 Kubernetes에 올린다는 것](01-kubernetes-and-regtest.md) | 1: 기반·regtest |
| 2 | [Helm으로 LND 설정하기: Chart에서 StatefulSet까지](01a-helm-chart-and-templates.md) | 1~2: Helm 구성 |
| 3 | [Helm 설치 뒤에 남은 일: testnet 지갑과 동기화](02-testnet-wallet-and-sync.md) | 2: 지속 testnet 노드 |
| 4 | [채널은 연결이 아니었다: 잔액과 유동성 이해하기](03-channels-and-liquidity.md) | 3: 라우팅 준비 |
| 5 | [송금 성공과 중계 성공을 따로 확인한 이유](04-payments-and-forwarding.md) | 3: 실제 중계 |
| 6 | [Loop Out 세 번의 실패: 시간을 늘려도 해결되지 않은 문제](05-loop-success-and-failure.md) | 4: Loop |
| 7 | [Grafana가 이미 있었다: 기존 설치를 찾아 관측 연결하기](06-prometheus-and-grafana.md) | 5: 관측 구축 |
| 8 | [지표에서 경보로: lndmon과 PrometheusRule의 역할](07-metrics-and-alerts.md) | 5: 규칙·검증 |

실습 장비와 VM 자원은 [1편의 환경 표](01-kubernetes-and-regtest.md#실습-장비와-클러스터-자원)에 정리했다. 현재 확인된 소스 설정과 아직 확인되지 않은 물리 장비 사양을 구분한다.

7편에는 기존 LND StatefulSet의 관측 sidecar, Prometheus의 대상 탐색·label 부여, Grafana 데이터 소스·ConfigMap 연결을 실제 설정 기준으로 설명했다. 새 관측 스택 설치가 아니라 기존 배포를 이해하고 수정 위치를 찾는 내용이다.

## 기록 기준

작성일은 2026-09-29다. 2026-09-23~28의 저장된 검증 문서, 운영 결과 파일, 실습 대화의 명령 출력과 화면을 대조했다. 작성 시점에 Mac Kubernetes API와 WSL SSH를 다시 조회하려 했지만 실행 환경에서 `operation not permitted`로 차단됐다. 따라서 이 글들은 **실습 당시 결과**이며 현재 클러스터가 동일하게 동작한다는 실시간 확인은 아니다.

이전 문서의 Phase 번호와 현재 메뉴 번호는 다르다. 이 연재는 `ops/start`의 현재 순서를 기준으로 한다. 예전 문서의 testnet Phase 1은 현재 Phase 2, observability Phase 3은 현재 Phase 5에 해당한다. 과거 검증 기록을 최근에 다시 수행한 실습처럼 서술하지 않는다.

실습은 regtest와 testnet을 사용했다. 실제 상용 자금 운영·수익성·고가용성 검증을 주장하지 않는다. 온체인 주소·전체 노드 공개키·결제 식별자와 개인 장비 주소는 게시물에 옮기지 않았다. 시드·macaroon·인보이스·preimage·비밀번호는 포함하지 않는다.

## 편집 및 검증 메모

- [근거 목록](evidence-notes.md)은 편집용이며 게시물 본문과 구분한다.
- 코드 블록의 명령은 설명용이다. 새 결제·채널 개설·삭제 명령은 독자가 그대로 실행하게 싣지 않았다.
- Mac 관측 실습에서 실제 확인된 namespace는 `lnd-monitoring`이다. 현재 소스의 기본값 `lndops-monitoring`과 혼용하지 않는다.
- Phase 3은 중계 실습 성공과 전체 완료를 구분한다. 이후 조회에는 정책 미충족·외부 접속 미검증이 남았다.
- Phase 4는 Mac의 저장된 성공 증거와 WSL의 세 차례 실패 후 보류를 함께 기록한다.
- Phase 5는 UI·scrape·규칙 평가를 확인했다. 이번 수동 실습에서 장애 주입과 외부 알림 전달을 새로 검증한 것은 아니다.

이 초안은 저장소 안에만 작성했으며 블로그에 게시하지 않았다.
