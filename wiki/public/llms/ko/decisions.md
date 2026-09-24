# ADR 색인

> 시스템 전체에 영향을 주는 기술 선택과 대안

ADR 색인


이 페이지는 설치된 도구의 목록을 반복하기보다, 어떤 요구 때문에 선택했으며 어느 조건에서 다시 판단할지를 기록한다. 아래 기록은 현재 구현을 해석한 설계 메모다. 별도 승인 절차를 거친 상세 ADR 전체가 작성되었다는 뜻은 아니다.

ADR-001: 로컬 단일 노드 K3s

목표는 Mac과 Windows의 서로 다른 Linux 실행 환경에서 동일한 workload와 정책을 검증하는 것이었다. K3s를 선택하면 로컬에서 control plane을 포함한 Kubernetes를 운영하면서 Helm·RBAC·NetworkPolicy를 사용할 수 있다. 반대 선택인 systemd나 Compose는 단일 LND 실행에는 더 단순하지만 이 프로젝트가 시험하려는 Kubernetes 운영 계약을 제공하지 않는다.

그 대가로 control plane, storage provisioner, CNI와 host 네트워크를 함께 진단해야 한다. 단일 노드이므로 HA를 제공하지 않는다. 다중 운영자나 외부 서비스의 가용성 목표가 생기면 회고의 실패 모델을 기준으로 재검토한다.

ADR-002: 노드별 StatefulSet과 PVC

LND는 신원과 채널 상태를 유지해야 하므로 실행 프로세스와 데이터의 수명을 분리했다. 각 StatefulSet은 replicas 1이고 별도 PVC를 가진다. regtest의 두 노드는 한 지갑의 복제본이 아니라 독립된 두 identity다.

Deployment에 PVC를 수동 연결하는 대안도 가능하지만 이 프로젝트에서는 정해진 Pod 이름과 claim 관계를 검증하기 쉽도록 StatefulSet을 사용한다. StatefulSet이 저장소 복제나 channel DB의 무결성을 보장하지 않는다는 비용·경계는 Kubernetes 설계에 설명한다.

ADR-003: regtest와 testnet 분리

반복 fault 실험에는 채굴과 peer, 결제 흐름을 통제할 수 있는 환경이 필요하다. 동시에 공개 네트워크와 연결되는 실제 프로토콜 동작도 확인하고 싶었다. 두 목적을 별도 namespace와 values로 분리했다.

따라서 regtest의 성공을 testnet 모든 경로의 성공률로 확대하지 않는다. mainnet으로 확장하려면 자금 관리, 백업, 가용성, 운영 권한을 별도 검토해야 한다. 관련 흐름은 채널과 결제에 있다.

ADR-004: Prometheus와 Grafana

관측값과 alert, 대시보드 쿼리를 코드로 비교하고 같은 배포에서 반복 검사하는 것이 필요했다. Prometheus는 시계열과 rule을, Grafana는 운영 질문별 화면을 제공한다. 외부 관리형 관측 서비스는 host 밖 장애 경계를 얻을 수 있지만 계정·연결·비용 관리가 추가된다.

현재는 로컬 재현성을 우선했고 그 결과 host 자체 중단을 내부에서 알릴 수 없다는 한계가 생겼다. 장기 다중 cluster 운영이나 외부 SLO가 생기면 저장과 알림 경계를 재검토한다. 관측 장에서 실제 신호와 제약을 읽는다.

ADR-005: admission과 runtime 탐지 분리

잘못된 Pod spec과 실행 후 발생하는 행위는 관측 시점이 다르다. Kyverno로 workload 조건을 강제하고 Falco로 runtime event 전달을 시험한다. 정책 작성과 센서의 높은 권한, rule 유지보수라는 비용을 함께 받아들인 선택이다.

둘을 설치했다고 완전한 침해 방지가 되는 것은 아니다. 보안 장에서 RBAC와 network, 공유 volume 예외까지 함께 검토한다.

ADR-006: 외부 Ollama와 제한된 gateway

현재 사용 가능한 Mac 모델 서버를 재사용하면서 Windows cluster의 진단 경로를 시험한다. cluster 안에 모델 서버를 추가하는 대신 LAN 접근과 모델 서버 가용성에 의존한다. 모델 연결이 끊겨도 LND 자체가 중지되지는 않지만 AI 진단은 사용할 수 없다.

모델에게 일반 kubectl을 주는 대신 고정된 MCP 도구와 한 개의 probe 조치만 제공한다. 도구의 유연성을 줄이는 대가로 실행 권한을 결정적으로 제한한다. 실제 승인 API와 일반 LND 복구는 자동 대응 장의 향후 범위다.

ADR-007: Vault 도입 보류

현재는 지갑 암호와 복구 입력을 운영자가 직접 다루며 Vault가 배포되어 있지 않다. 단일 사용자 로컬 환경에 Vault를 추가하면 자체 storage·unseal·복구 운영이 생긴다. 우선 해결할 문제가 단순한 도구 부재인지, 중앙 비밀 회전·다중 사용자 권한인지를 구분한다.

다중 운영자와 자격 증명 수명주기 요구가 생기면 도입을 재검토한다. same-host backup의 장애 경계나 disk 암호화는 Vault 설치와 별도 문제다. 구체적인 근거는 지갑과 복구 경계에 있다.
