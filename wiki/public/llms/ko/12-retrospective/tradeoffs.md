# 한계와 다음 단계

> 현재 로컬 단일 노드 설계가 증명한 것과 증명하지 않은 것을 구분한다

한계와 다음 단계


현재 프로젝트는 재현 가능한 단일 노드 운영, 지갑 보존 재배포, 관측, 정책, 장애·복구, 제한된 LLM 대응을 증명했다. 다음은 증명하지 않았다.

- mainnet 자금 운영과 고가용성
- 다중 노드 storage failover
- 외부에서 host·cluster 중단을 감지하는 가용성 감시
- 실제 receive failure 관측
- Windows 전체 볼륨 암호화 완료
- 일반화된 LND 자동 remediation
- 장기 로그와 감사 이벤트 보존

확장은 “도구 추가”보다 실패 모델과 불변 조건을 먼저 정의한다. 다중 노드 전환이라면 storage topology, 동일 identity 중복 실행 방지, fencing, backup RPO/RTO를 우선 설계해야 한다.
