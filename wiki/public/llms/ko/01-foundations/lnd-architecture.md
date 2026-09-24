# LND 구조와 상태

> LND가 Bitcoin, Lightning peer, wallet, channel 상태를 어떻게 연결하는지 설명한다

LND 구조와 상태



먼저 잡아야 할 모델

LND는 단순한 HTTP 서버가 아니다. Bitcoin 체인의 상태를 따라가고, 장기간 유지되는 노드 키로 peer와 연결하며, 채널 상태를 로컬 데이터베이스에 보관하고, 결제 HTLC를 시간 제약 안에서 처리한다. 따라서 프로세스를 다시 띄우는 것만으로 노드를 복구했다고 말할 수 없다.



상태별 역할

| 상태 | 역할 | 잃었을 때의 의미 | 이 프로젝트의 취급 |
| --- | --- | --- | --- |
| aezeed | 온체인 키 복구의 근원 | 자금 복구 능력 상실 | 사용자만 기록, 저장소와 자동화에서 제외 |
| wallet password | 로컬 wallet DB 잠금 해제 | 노드가 잠긴 상태로 기동 | 대화형 입력만 허용 |
| `wallet.db` | 온체인 지갑 상태 | seed 복구 절차 필요 | PVC에 영속화 |
| `channel.db` | 최신 채널 상태 | 오래된 상태로 임의 복원하면 위험 | 일반 파일 복사를 복구 수단으로 취급하지 않음 |
| SCB | 채널 상대에게 데이터 손실 복구를 요청하는 정적 백업 | 채널 복구 수단 하나를 잃음 | PVC 밖에 암호화 복사, 최신성 관측 |
| macaroon | RPC 권한 증명 | 노출 시 권한 범위 내 호출 가능 | readonly만 관측 sidecar가 읽음 |
| TLS 인증서 | RPC 서버 인증·암호화 | 클라이언트 연결과 신뢰 실패 | 만료 시각 관측, 수동 회전 runbook |



regtest와 testnet을 나눈 이유

regtest에는 Bitcoin Core와 LND 두 개를 함께 띄워 채굴, 채널 개설, 양방향 결제, 정책 차단, 복구를 통제된 환경에서 반복한다. testnet은 외부 네트워크와 실제 프로토콜 상호운용성을 보여주되 자금·채널 변경을 보수적으로 다룬다. 같은 Helm chart를 서로 다른 values로 렌더링해 구조 차이보다 운영 목적의 차이를 드러낸다.

| 요구사항 | 선택 | 대안 | 선택 이유 | 비용·한계 |
| --- | --- | --- | --- | --- |
| 재현 가능한 결제 실습 | 로컬 regtest 2노드 | testnet에서 반복 | 채굴·채널·장애를 통제 가능 | 실제 라우팅 시장을 재현하지 않음 |
| 외부 상호운용 증명 | testnet 1노드 | mainnet | 실자금 위험을 줄임 | testnet 유동성 품질이 불안정 |
| 체인 접근 | regtest bitcoind, testnet Neutrino | testnet full node | 로컬 자원과 초기 동기화 비용 절감 | Neutrino peer 가용성에 의존 |

무엇을 가지고 무엇을 복구하는가

| 잃은 상태 | 남은 입력 | 복구 가능한 것 | 피할 수 없는 결과 |
| --- | --- | --- | --- |
| 실행 중인 Pod | 기존 PVC | 같은 node identity와 channel 상태 | wallet 재잠금 가능 |
| wallet/PVC | aezeed만 | 온체인 wallet key와 발견된 온체인 자금 | channel 자동 복원 불가 |
| wallet/PVC | aezeed + 최신 SCB | 온체인 자금과 peer force close를 통한 channel 자금 회수 | 기존 channel은 닫힘 |
| 오래된 `channel.db` | aezeed 포함 | 상황별 수동 복구 후보 | 최신 commitment가 아니면 자금 위험; 임의 사용 금지 |
| aezeed와 wallet DB 모두 | SCB만 | 노드의 개인키를 재생성할 수 없음 | 자금 복구 불가 |

wallet password는 기존 `wallet.db`를 여는 값이고 aezeed를 대신하지 않는다. cipher seed passphrase는 암호화된 aezeed를 해독하는 값이며 wallet password와 다르다.

구현 근거

- `charts/lnd-ops/templates/lnd.yaml`: `/data/.lnd` PVC, RPC/P2P, regtest bitcoind와 testnet Neutrino 인자
- `charts/lnd-ops/values-regtest.yaml`: 두 LND 노드와 Bitcoin Core
- `docs/regtest-runbook.md`: 지갑·채널·양방향 결제 절차
- `docs/testnet-runbook.md`: testnet의 수동 자금 경계

읽기 전용 관찰



`getinfo`의 identity, sync 상태, peer 수는 프로세스가 어떤 노드로 동작하는지 보여준다. `listchannels`의 `active`, `local_balance`, `remote_balance`는 연결성과 방향별 유동성을 구분하는 출발점이다.

공식 원리

- LND 개발자 문서
- LND 데이터 손실 복구
- Lightning 유동성 설명

점검 문제

Pod가 재생성된 뒤 같은 PVC를 붙이면 왜 같은 Lightning 노드인가?노드 신원과 wallet/channel 데이터가 프로세스 이미지가 아니라 `/data/.lnd`의 영속 상태에 있기 때문이다. 단, wallet은 다시 잠길 수 있으므로 동일 신원과 운영 준비 상태는 별도 검사해야 한다.

SCB가 있으면 channel.db 백업은 필요 없다고 단순화할 수 있는가?SCB는 상대의 force close를 통해 자금을 회수하기 위한 복구 수단이다. 정상 운영 상태의 즉시 복원과 동일하지 않으므로 RTO와 채널 유지 관점에서 구분해야 한다.

면접 질문

> LND를 일반적인 stateless Deployment로 운영했을 때 가장 위험한 실패 모드는 무엇이며, readiness probe만으로 왜 막을 수 없는가?
