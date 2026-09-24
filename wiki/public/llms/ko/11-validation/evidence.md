# 증거 기반 검증

> 커밋, 플랫폼, 불변 조건을 비밀 없는 evidence로 연결한다

증거 기반 검증


acceptance evidence는 명령 출력 덤프가 아니다. schema, Git revision, host 유형, 통과한 불변 조건, 알려진 제약을 기록하며 seed, password, macaroon, invoice, payment hash, 원시 식별자는 제외한다.

- 교차 플랫폼 Phase 8 증거
- Windows Phase 7 kagent 증거
- Windows Phase 6 장애 증거

검증 상태는 `설계됨`, `자동 검증됨`, `실제 환경 검증됨`만 사용한다. 문서 CI는 모든 학습 페이지에 버전, 플랫폼, 날짜, 커밋, 상태, 적용 범위가 있는지 검사한다.

`근거 커밋`은 페이지 파일의 최신 커밋이 아니라 해당 주장의 acceptance가 통과한 revision이다. 본문을 윤문했다고 자동으로 바꾸지 않으며, 관련 검증을 다시 실행했을 때 갱신한다. `실제 환경 검증됨`은 연결된 evidence나 runbook에 재현 절차와 확인한 불변 조건이 있어야 한다.
