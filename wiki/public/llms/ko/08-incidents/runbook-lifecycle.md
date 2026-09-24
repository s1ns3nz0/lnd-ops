# 장애 대응 수명주기

> 증상, 근거, 조치, 복구 검증을 버전이 붙은 runbook으로 연결한다

장애 대응 수명주기


runbook은 명령 모음이 아니라 판단의 순서다: 증상을 확인하고, 파생 경보를 제거하고, 원인을 좁힌 뒤, 가장 작은 조치를 수행하고, 원래 불변 조건의 회복을 검증한다.



Phase 6은 channel 격리, CrashLoop, Falco marker를 실제로 주입하고 alert 전달과 복구를 검증했다. 상태 변경 실습은 `docs/phase9-demo-runbook.md`를 따른다.
