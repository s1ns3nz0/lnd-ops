---
title: Helm과 재현 가능한 배포
description: 빈 환경, 반복 배포, 다중 아키텍처를 하나의 계약으로 다룬다
versions: Helm 4.1.4 · K3s 1.36.4
platforms: macOS arm64 · Windows WSL2 amd64
verified: 2026-09-24
commit: 841692b
status: 실제 환경 검증됨
scope: regtest · testnet
---
# Helm과 재현 가능한 배포
<MetadataCard versions="Helm 4.1.4 · K3s 1.36.4" platforms="macOS arm64 · Windows WSL2 amd64" verified="2026-09-24" commit="841692b" status="실제 환경 검증됨" scope="regtest · testnet" />

재현성의 기준은 YAML이 렌더링되는가가 아니라 **리소스가 없는 호스트에서 bootstrap→deploy→verify가 통과하고, 기존 지갑 PVC를 보존한 재배포에서도 신원과 관측 이력이 유지되는가**다.

- digest 고정 image와 멀티 아키텍처 OCI index
- regtest/testnet은 같은 chart, 다른 values
- `helm upgrade --install`의 반복 적용
- 수동 지갑 경계를 exit code `10`으로 표현
- Mac arm64와 Windows WSL2 amd64의 실제 acceptance

```sh
ops/doctor
ops/bootstrap
ops/deploy regtest
ops/verify regtest
```

구현: [`ops/bootstrap`](https://github.com/s1ns3nz0/lnd-ops/blob/master/ops/bootstrap), [`ops/deploy`](https://github.com/s1ns3nz0/lnd-ops/blob/master/ops/deploy), [`docs/clean-start-runbook.md`](https://github.com/s1ns3nz0/lnd-ops/blob/master/docs/clean-start-runbook.md)

