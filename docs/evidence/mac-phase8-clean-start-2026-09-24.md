# Mac Phase 8 isolated clean-start evidence

Date: 2026-09-24  
Host: macOS arm64  
Runtime revision: `8d87e3e623511f21cc1b9d15672b8d3915627dfe`

## Result

`ops/exercise-clean-start --cleanup` passed against a separate Lima VM named
`lnd-ops-phase8-clean`. The production-style Mac cluster and its wallet PVCs
were not changed. The exercise began with the isolated VM absent and used a
separate owner-only state directory and Kubernetes API forwarding port.

The repository scripts then performed all of these operations without editing
generated Kubernetes manifests:

- created the Lima VM and installed K3s `v1.36.4+k3s1` with Secret encryption;
- reran `ops/bootstrap` successfully against the existing isolated cluster;
- installed wallet-free regtest and testnet releases;
- observed the explicit exit `10` wallet gates for both profiles;
- installed Prometheus, Grafana, Alertmanager, and their persistent storage;
- passed `ops/verify-monitoring --infrastructure-only`;
- installed enforced Kyverno policy and the Falco modern eBPF stack;
- reapplied both profile charts and advanced each Helm revision from 1 to 2;
- verified the node, Bitcoin Core, both LND profiles, monitoring, Kyverno, and
  Falco workloads before deleting only the isolated VM.

The private evidence record
`phase8-clean-start-mac-20260924T120732.json` is operator-owned mode `0600` and
has SHA256
`6feb7a7786caeb5e6a12b57e9acb10ae162a7b504da1e64c4006815576e4b973`.
It records no wallet or cluster credential.

## Remaining functional gate

This is the wallet-free infrastructure proof. The separate persistent Mac
testnet wallet, funding, public channel, bidirectional payment, encrypted SCB,
live monitoring, security acceptance, and wallet-preserving redeployment proof
remain required before Phase 8 is complete.
