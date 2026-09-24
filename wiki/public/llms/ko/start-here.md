# 안전하게 시작하기

> 읽기 전용 학습, 기존 클러스터 관찰, regtest 실습의 시작 조건과 안전 경계

안전하게 시작하기


배경지식부터 읽는 순서

클러스터가 없어도 본문은 읽을 수 있다. 먼저 LND 구조에서 UTXO, funding transaction, commitment를 읽고 “키 복원과 최신 채널 상태 복원은 왜 다른가”를 설명해 본다. 이어서 채널과 유동성의 두 노드 잔액 계산을 해 보면 총 capacity와 송수신 가능량을 구분할 수 있다.

그다음 Kubernetes 설계에서 선언이 Pod와 디스크로 연결되는 과정을 따라간다. 관측은 그 상태를 어떤 시간 표본으로 읽는지, 보안은 누가 어느 경로로 접근하는지, 자동 대응은 그 관측과 권한을 모델에 어떻게 제공하는지를 설명한다.

각 장의 수치 예시는 계산 원리를 배우기 위한 것이다. 현재 코드의 실제 임계값과 검증 결과는 본문에서 별도로 표시한다. 기초 설명을 읽은 뒤 구현 근거를 열어 “이 원리가 이 파일의 어떤 설정으로 표현됐는가”를 연결하는 방식으로 공부한다.

먼저 모드를 고른다

| 모드 | 필요한 환경 | 상태 변경 | 시작점 |
| --- | --- | --- | --- |
| 읽기만 | 브라우저 | 없음 | 학습 지도 |
| 기존 환경 관찰 | 배포된 lnd-ops와 kubeconfig | 없음 | 아래 읽기 전용 점검 |
| 로컬 regtest 실습 | 준비된 Mac 또는 Windows WSL2 | regtest만 변경 | clean-start runbook |
| testnet 검증 | 자금·채널이 있는 기존 testnet 노드 | 기본 경로는 읽기 전용 | testnet runbook |

처음에는 **기존 환경 관찰**로 시작한다. 다음 명령은 Kubernetes나 LND 상태를 변경하지 않는다.

첫 읽기 전용 점검



기대 결과는 Kubernetes node가 `Ready`이고, LND Pod와 PVC 관계가 출력되며, 마지막 명령이 실행할 읽기 전용 1~3단계 계획을 보여주는 것이다. `Unauthorized`, `connection refused`, `Pending PVC`가 나오면 실습을 진행하지 말고 Windows runbook 또는 clean-start runbook에서 환경을 복구한다.

안전 규칙

1. 장애 주입과 복구는 regtest에서 먼저 수행한다.
2. seed, cipher seed passphrase, wallet password, macaroon, payment request를 문서·Git·로그·LLM 입력에 붙이지 않는다.
3. `delete`, wallet unlock, payment, channel open/close, recovery 명령은 해당 runbook의 선행 조건을 확인한 뒤 실행한다.
4. testnet에서는 명령이 읽기 전용인지 확인하고, 자금 이동은 운영자가 금액과 목적지를 직접 검토한다.
5. recovery namespace나 같은 pubkey의 두 LND가 보이면 추측해서 정리하지 않는다.

페이지 메타데이터 읽기

| 항목 | 의미 |
| --- | --- |
| 관련 버전 | 설명과 검증에 사용한 핵심 버전 |
| 검증 플랫폼 | 실제로 수행했거나 자동 검사한 환경 |
| 마지막 검증 | 코드 작성일이 아니라 근거를 다시 확인한 날짜 |
| 근거 커밋 | 설명한 acceptance/evidence가 통과한 Git revision; 문서 수정마다 자동 변경하지 않음 |
| 설계됨 | 의도와 경계가 문서화됐지만 실행 증거가 없음 |
| 자동 검증됨 | CI나 결정적 테스트가 통과함 |
| 실제 환경 검증됨 | 대상 Mac/Windows 클러스터에서 acceptance를 통과함 |
| 적용 범위 | regtest, testnet 중 어느 환경에 근거가 있는지 표시 |

완료 조건

- 현재 context와 API server가 의도한 로컬 클러스터다.
- node가 `Ready`다.
- Pod가 어떤 PVC를 쓰는지 설명할 수 있다.
- dry-run의 1~3단계가 왜 읽기 전용인지 설명할 수 있다.
- 비밀과 자금 조작이 학습 명령에서 분리됐음을 확인했다.

다음은 LND 구조와 상태다.
