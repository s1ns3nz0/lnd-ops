# Phase 8 cross-platform acceptance evidence

Validation date: 2026-09-24  
Hosts: macOS arm64 and Windows 11 Home with WSL 2 Ubuntu amd64

## Result

Phase 8 passed on both target host platforms. Each host used the same clean
Git revision and the command surface defined in the
[Phase 8 runbook](../phase8-runbook.md). The final
`ops/phase8-acceptance` gate required fresh owner-only host records and both
GitHub Actions workflows for that exact revision.

The Mac clean-start exercise created a separate wallet-free Lima and K3s
environment from repository scripts, reapplied the stack, verified the
infrastructure, monitoring, Kyverno, and Falco workloads, and removed only the
isolated environment. The persistent Mac cluster retained its funded wallet
and channel throughout the functional checks.

Both persistent hosts independently proved:

- a synchronized Lightning testnet node with external peers and an active
  public channel;
- successful recent outgoing and settled incoming Lightning payments;
- current AES-256 encrypted static channel backup integrity;
- live LND, channel, liquidity, payment, Kubernetes, backup, and security
  telemetry;
- peer reconnection after an LND Pod restart;
- preserved node identity, channel, LND PVC, Prometheus PVC, SCB, and an exact
  historical Prometheus sample across ordinary Helm reapplication;
- enforced Kyverno admission rules, scoped RBAC, NetworkPolicy isolation, a
  real Falco event delivered to Alertmanager, and live TLS expiry telemetry.

## Acceptance chain

The final run executed these gates without recording credentials, wallet
seeds, macaroons, invoices, payment preimages, or raw SCBs:

```sh
ops/backup-status-encrypted testnet lnd-0
ops/redeploy-check
ops/verify-monitoring --profile testnet
ops/testnet-status
ops/acceptance testnet
ops/phase4-acceptance
ops/phase8-host-acceptance
ops/phase8-acceptance /path/to/windows-phase8-host.json
```

This page is the redacted public summary. The authoritative machine-readable
JSON evidence remains under each operator's
`${XDG_STATE_HOME:-$HOME/.local/state}/lnd-ops/evidence/` directory with mode
`0600`. The cross-host file contains only host labels, Git revisions, evidence
filenames, hashes, CI workflow names, and pass results. It contains no wallet
or payment material.

## Scope boundary

Phase 8 proves reproducible deployment and equivalent live operation on the
two target platforms. Phase 9 remains the rehearsed public portfolio demo,
including the five-minute narrative, captured visuals, and final presentation
artifacts.
