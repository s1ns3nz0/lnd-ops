---
title: 지갑과 복구 경계
description: seed, password, macaroon, TLS, SCB의 서로 다른 보안 역할
versions: LND pinned image
platforms: macOS arm64 · Windows WSL2 amd64
verified: 2026-09-24
commit: 841692b
status: 실제 환경 검증됨
scope: regtest · testnet
---
# 지갑과 복구 경계
<MetadataCard versions="LND pinned image" platforms="macOS arm64 · Windows WSL2 amd64" verified="2026-09-24" commit="841692b" status="실제 환경 검증됨" scope="regtest · testnet" />

LND 설치 중 “passphrase를 입력하라”는 안내를 여러 번 만나면 같은 비밀번호를 다시 묻는다고 생각하기 쉽다. 실제로는 로컬 지갑을 여는 암호, seed를 해독하는 암호, SCB 백업 파일을 해독하는 암호가 서로 다른 자산을 보호한다. 운영 자동화를 설계하려면 먼저 이 역할을 분리해야 한다.

## 배경: 키, 잠금, 접근 권한은 서로 다른 문제다

지갑의 개인키는 거래에 서명할 능력을 제공한다. seed는 필요한 키를 다시 유도하기 위한 출발점이다. 여기서 **결정적 유도**란 같은 입력과 규칙으로 같은 키를 다시 얻는다는 뜻이다. 그러나 키를 재생성하는 것과 peer와 교환한 최신 채널 상태를 재생성하는 것은 다르다. seed에 모든 채널 갱신 이력이 들어 있는 것은 아니다. 그래서 seed 보관만으로 운영 중인 채널의 즉시 복원까지 해결됐다고 할 수 없다. [LND 복구 경계](https://docs.lightning.engineering/lightning-network-tools/lnd/disaster-recovery)

wallet password는 기존 지갑을 열 때 사용하는 값이다. 이를 바꾸거나 알고 있다는 사실이 과거에 기록한 seed를 대체하지는 않는다. 또한 백업 파일을 암호화할 때 사용하는 passphrase는 그 백업을 여는 값이다. 서로 다른 암호를 한 단어로 “지갑 비밀번호”라고 부르면 재시작과 복구 과정에서 혼동하기 쉽다. 아래 절에서는 각각 어느 입력 화면과 파일에 대응하는지 구분한다.

## 배경: 암호화된 통신에도 권한 검사가 필요하다

TLS는 연결 상대를 인증하고 통신 중의 내용을 보호하는 계층이다. macaroon은 LND RPC에서 어떤 작업을 허용할지 검사하는 자격 증명이다. 이를 출입구에 비유하면 TLS는 올바른 건물로 안전하게 이동하는 과정, macaroon은 건물 안에서 출입 가능한 방을 정하는 증명에 가깝다. 비유와 달리 실제 검증은 인증서와 RPC 권한 규칙으로 수행된다. [LND macaroon 설명](https://docs.lightning.engineering/lightning-network-tools/lnd/macaroons)

따라서 HTTPS로 연결했어도 과도한 권한의 macaroon이 노출되면 문제가 된다. 반대로 readonly macaroon을 쓰더라도 같은 프로세스가 wallet 파일 전체를 읽을 수 있다면 파일 접근 위험은 남아 있다. RPC 권한과 파일시스템 권한은 서로 다른 경로이기 때문이다.

이 프로젝트의 관측 sidecar에는 읽기 전용 볼륨 마운트가 있다. 여기서 읽기 전용은 그 마운트를 통한 쓰기를 막는다는 뜻이며, 필요한 파일만 보이게 한다는 뜻은 아니다. 다음 개선을 검토할 때는 “수정 못 한다”와 “민감한 파일을 읽지 못한다”를 따로 시험해야 한다. 현재 한계를 이해해야 Vault 같은 추가 도구가 실제로 어느 경계를 바꿀지도 판단할 수 있다.


## 재시작 뒤 잠긴 지갑은 데이터 손실이 아니다

LND는 기존 wallet 데이터가 있어도 잠긴 상태로 시작할 수 있다. wallet password는 그 로컬 데이터베이스를 여는 데 사용한다. 운영자가 unlock하면 기존 신원과 상태로 서비스를 재개할 수 있으며, 이때 새 지갑을 만드는 것은 잘못된 대응이다.

이 프로젝트는 암호를 Helm values나 환경 변수에 저장하지 않는다. 그렇게 저장하면 배포가 쉬워지는 대신 클러스터 안에서 암호를 읽을 수 있는 주체가 늘어난다. 현재 선택은 운영자가 재시작 후 직접 unlock하고 자동화는 그 대기를 알리는 방식이다. 즉 무인 기동의 편의보다 지갑 접근 권한의 범위를 좁히는 데 무게를 두었다.

## seed와 세 가지 암호의 역할

seed인 aezeed는 복구에 필요한 키 재료다. wallet password를 잊어도 올바른 seed와 필요한 추가 입력이 있으면 별도 복구 절차를 검토할 수 있지만, password만으로 seed를 대신할 수는 없다. aezeed 자체를 암호화했다면 cipher seed passphrase도 필요하다.

SCB 암호화에 사용하는 GPG passphrase는 또 다른 값이다. 이것은 호스트에 복사한 백업 파일을 해독하며, LND wallet을 열지 않는다. 반대로 wallet password를 안다고 암호화된 SCB가 자동으로 풀리지 않는다. 생성 시 운영자가 seed를 확인하는 행위는 필요하지만, 이를 채팅·녹화·일반 로그에 남기는 것은 피해야 한다.

## TLS와 macaroon은 다른 질문에 답한다

TLS 인증서는 클라이언트가 연결한 서버를 확인하고 통신을 보호하는 데 사용한다. macaroon은 해당 호출자가 어느 RPC를 실행할 수 있는지 나타낸다. 암호화된 연결이라고 모든 호출이 허용되는 것도 아니고, 올바른 macaroon이 있다고 서버 신뢰 확인을 생략할 수 있는 것도 아니다.

관측 sidecar는 읽기 전용 macaroon으로 상태를 조회한다. 다만 현재 템플릿은 필요한 파일만 별도 볼륨으로 잘라 제공하는 대신 전체 `/data` 볼륨을 read-only로 마운트한다. **읽기 전용 마운트는 쓰기를 막지만 민감 파일의 열람을 모두 차단하지 않는다.** 따라서 sidecar 침해를 LND와 완전히 분리된 보안 영역으로 간주할 수 없다. 파일별 최소 노출은 후속 보강 대상이다.

## Vault와 cert-manager를 지금 설치하지 않은 이유

Vault는 비밀의 발급·회전·접근 감사 요구가 생기면 도움이 된다. 하지만 지갑과 같은 단일 PC의 클러스터 안에 Vault를 둔다고 host disk 상실의 복구 경계가 분리되지는 않는다. Vault의 저장소, 초기화와 unseal, 장애 시 접근 복구까지 운영해야 한다. 현재 이 프로젝트에 Vault가 배포됐다고 설명하지 않으며, 다중 운영자나 중앙 비밀 회전이 필요해질 때 재검토한다.

cert-manager 역시 인증서를 생성하는 도구를 추가하는 것만으로 LND가 새 인증서를 읽고 모든 클라이언트가 신뢰하도록 만들지는 않는다. 현재는 LND가 소유하는 인증서의 만료를 관측하고 수동 회전 절차를 사용한다. issuer와 LND의 갱신·재시작·신뢰 배포 계약을 정한 뒤 자동화하는 순서가 필요하다.

## 읽기 전용으로 권한 배치를 확인하기

```sh
kubectl -n lnd-testnet get statefulset lnd-0 -o yaml
kubectl -n lnd-testnet get serviceaccount lnd-node -o yaml
```

출력에서 sidecar의 `readOnly` 마운트, `readonly.macaroon` 경로, ServiceAccount token 자동 마운트 비활성화를 찾는다. macaroon의 실제 바이트를 출력할 필요는 없다. 각각 파일 변경, LND RPC 권한, Kubernetes API 접근이라는 서로 다른 경계를 설명할 수 있으면 된다.

실제 파일 배치는 [`lnd.yaml`](https://github.com/s1ns3nz0/lnd-ops/blob/master/charts/lnd-ops/templates/lnd.yaml), 수동 입력의 의미는 [testnet runbook](https://github.com/s1ns3nz0/lnd-ops/blob/master/docs/testnet-runbook.md)에 있다. 복구 원리는 [LND 공식 복구 문서](https://docs.lightning.engineering/lightning-network-tools/lnd/disaster-recovery)를 따른다.

<details class="quiz"><summary>readonly macaroon과 read-only volume을 쓰면 sidecar에서 wallet 데이터가 완전히 격리되는가?</summary>아니다. 전자는 사용한 RPC 자격 증명의 권한이고 후자는 파일 쓰기 제한이다. 현재 공유 볼륨에서 읽을 수 있는 다른 파일과 같은 Pod의 통신 경계도 따로 검토해야 한다.</details>

다음 [채널과 유동성](/06-payments/channel-liquidity)에서 지갑이 열린 이후에도 결제가 실패하는 이유를 살펴본다.
