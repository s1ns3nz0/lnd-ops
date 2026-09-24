---
title: Kubernetes 심층 방어
description: NetworkPolicy, RBAC, Kyverno, Falco가 서로 다른 실패 단계를 다루는 이유
versions: Kubernetes 1.36 · Kyverno 3.9.1 · Falco 9.2.0 chart
platforms: macOS arm64 · Windows WSL2 amd64
verified: 2026-09-24
commit: 841692b
status: 실제 환경 검증됨
scope: regtest · testnet
---
# Kubernetes 심층 방어
<MetadataCard versions="Kubernetes 1.36 · Kyverno 3.9.1 · Falco 9.2.0 chart" platforms="macOS arm64 · Windows WSL2 amd64" verified="2026-09-24" commit="841692b" status="실제 환경 검증됨" scope="regtest · testnet" />

| 통제 | 막거나 발견하는 것 | 막지 못하는 것 |
| --- | --- | --- |
| Pod securityContext | privilege escalation과 Linux capability | 허용된 프로세스의 논리 오류 |
| Kyverno | 잘못된 workload가 입장하는 것 | 이미 실행 중인 runtime 행위 |
| RBAC | Kubernetes API 권한 남용 | Pod 간 네트워크 접근 |
| NetworkPolicy | 불필요한 ingress/egress | host·CNI 바깥의 방화벽 역할 |
| Falco | 실행 후 의심스러운 runtime event | 사전 차단과 비즈니스 의미 판단 |
| digest pin | tag 변조와 예기치 않은 이미지 교체 | 고정된 이미지 자체의 취약점 |

보안은 하나의 도구로 완성되지 않는다. admission, identity, network, runtime, recovery 단계에 다른 통제를 둔다. 자세한 예외와 acceptance는 [`docs/security-baseline.md`](https://github.com/s1ns3nz0/lnd-ops/blob/master/docs/security-baseline.md)에 있다.

### 면접 질문
> NetworkPolicy가 적용되어도 host firewall과 egress proxy가 별도 관심사인 이유는 무엇인가?

