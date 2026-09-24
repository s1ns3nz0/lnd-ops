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

처음 설치할 때는 파일 몇 개와 명령 순서를 기억하는 것으로 충분해 보인다. 하지만 Mac에서 성공한 설치를 Windows에서 반복하거나, 지갑이 있는 환경에 새 설정을 적용하면 그 기억은 배포 계약이 되지 못한다. 이 장은 설치 과정에서 무엇을 고정하고 무엇을 환경별 입력으로 남겼는지 설명한다.

## 호스트 준비와 애플리케이션 배포를 나눈 이유

Mac에서는 Lima가 Linux 실행 환경을 제공하고, Windows에서는 WSL2가 그 역할을 한다. 이후의 K3s와 Helm 리소스는 공통으로 유지한다. [`ops/bootstrap`](https://github.com/s1ns3nz0/lnd-ops/blob/master/ops/bootstrap)은 호스트별 차이를 처리하고, [`ops/deploy`](https://github.com/s1ns3nz0/lnd-ops/blob/master/ops/deploy)는 준비된 Kubernetes에 애플리케이션을 적용한다.

이 경계를 나누면 LND 설정을 바꾸기 위해 VM을 다시 만들 필요가 없다. 반대로 컨테이너 안의 오류를 해결하려고 호스트 설치부터 반복하지도 않게 된다. preflight는 필요한 도구와 접근 조건을 확인하는 단계이지, LND의 채널 상태를 증명하는 단계는 아니다.

## Helm이 표현하는 것과 표현하지 않는 것

chart는 Service, StatefulSet, NetworkPolicy, ServiceAccount와 같은 원하는 리소스 형태를 표현한다. values는 regtest의 두 LND와 Bitcoin Core, testnet의 Neutrino 사용처럼 환경에 따른 차이를 담는다. 두 환경을 별도 YAML 복사본으로 관리하면 보안 수정 하나를 두 곳에 적용해야 하므로, 공통 구조를 템플릿으로 유지한다.

그러나 Helm은 지갑의 의미를 모른다. release 상태가 deployed라는 사실은 wallet이 열렸거나 채널이 active라는 뜻이 아니다. `upgrade --install`도 애플리케이션 차원의 안전한 재실행을 보장하지 않는다. 스크립트가 기존 지갑을 덮어쓰지 않고, monitoring 설정을 유지하며, 결과를 별도 verifier로 확인해야 반복 배포가 된다.

## 왜 tag 대신 digest를 고정하는가

이미지 tag는 다른 바이트를 가리키도록 바뀔 수 있다. digest를 고정하면 어느 이미지 집합을 사용했는지 식별할 수 있다. 이 저장소는 [`ops/images.lock.json`](https://github.com/s1ns3nz0/lnd-ops/blob/master/ops/images.lock.json)과 `ops/check-images`로 이미지와 플랫폼 지원을 관리한다.

Mac arm64와 Windows amd64는 서로 다른 CPU 명령어를 실행한다. 멀티 아키텍처 OCI index는 각 플랫폼의 이미지 manifest를 묶으며, 같은 index digest에서 호스트에 맞는 이미지를 선택한다. 따라서 “digest가 같음”과 “플랫폼별 바이너리가 같음”을 혼동하지 않는다. 실제 확인할 것은 두 플랫폼 모두에 manifest가 있고 동일 기능을 수행하는가다.

## 설치 실패를 읽는 순서

`StatefulSet not ready`는 원인이 아니라 제한 시간 안에 목표에 도달하지 못했다는 결과다. Pod가 Pending이면 scheduling과 PVC event를 먼저 본다. PVC가 Pending이면 provisioner가 동작하는지 확인한다. provisioner가 Kubernetes API에 연결하지 못하면 LND 이미지나 지갑을 바꾸는 것은 해결책이 아니다.

```sh
kubectl -n lnd-regtest get pods,pvc
kubectl -n lnd-regtest get events --sort-by=.lastTimestamp
kubectl -n kube-system get pods
```

이 명령은 기존 환경을 관찰한다. Pod에 node가 배정됐는지, claim이 Bound인지, image pull이나 scheduling event가 무엇인지에 따라 다음 점검 대상을 고른다.

## 빈 환경과 재배포는 별도의 시험이다

빈 환경 시험은 누락된 사전 준비를 찾는다. 지갑 보존 재배포 시험은 이미 있는 데이터를 유지하는지 확인한다. 현재 완료 기준에서는 지갑 재사용을 허용하지만, 그 결과를 seed 복구 시험으로 취급하지 않는다. 상세 절차는 [clean-start runbook](https://github.com/s1ns3nz0/lnd-ops/blob/master/docs/clean-start-runbook.md)에 있고, 일반 재배포의 상태 비교는 [`ops/redeploy-check`](https://github.com/s1ns3nz0/lnd-ops/blob/master/ops/redeploy-check)에 있다.

<details class="quiz"><summary>Helm 재실행이 성공했는데 왜 PVC UID와 노드 공개키를 다시 확인할까?</summary>선언된 리소스를 적용하는 성공과 기존 애플리케이션 상태를 보존하는 성공이 다르기 때문이다. 잘못된 claim을 붙여도 프로세스는 정상 기동할 수 있다.</details>

다음 [지갑과 키](/05-wallet/wallet-boundaries)에서는 배포 자동화가 멈추는 지점을 설명한다.
