# Windows Phase 3 integrated operations evidence

Validation completed: 2026-09-24 06:48:34 UTC  
Host: Windows 11 Home, WSL 2 Ubuntu, linux/amd64  
Tested Git revision: `14487d13682417bcaf920e9df5163907e3197bfa`

## Result

Phase 3 passed on the preserved testnet node with its existing public channel. The validation used the existing wallet, channels, LND PVC, Prometheus PVC, encrypted SCB, and historical metrics. It did not recreate a wallet, open or close a channel, initiate a payment, or replace either PVC.

## Evidence

1. The wallet reported `SERVER_ACTIVE`, and the encrypted off-PVC SCB plaintext SHA-256 recorded by the backup job equaled the live SCB SHA-256. Hash values remain only in private evidence.
2. `ops/verify-monitoring --profile testnet` exited `0` with live Grafana, Prometheus, Alertmanager, Kubernetes, disk, LND, wallet-state, lndmon, chain, and send/receive payment samples from the preceding hour.
3. `ops/verify-dashboards` exited `0` after verifying six Git-provisioned dashboards, 54 panels, 54 syntactically valid and nonempty live PromQL query results, and 14 alert rules with successful evaluation health. Every rule linked to a runbook present at the tested Git revision; rules could be inactive or firing according to live conditions.
4. `ops/redeploy-check` advanced `lnd-ops` and `lnd-ops-monitoring` from revision 5 to 6. Its before/after snapshots compared stable claim UIDs and preserved the node identity, two open channels, both PVCs, the current SCB, and the same timestamp and value from a historical `up{job="node-exporter"}` series.
5. `ops/phase3-acceptance` reran Phase 1 continuity, monitoring, backup, dashboard, query, alert, and runbook checks as one cluster-read-only gate and exited `0`.
6. The private machine-readable result was written with mode `0600` under the operator state directory. It records the tested commit and Kubernetes context without wallet secrets, SCB bytes or hashes, macaroons, payment requests, or payment hashes.

## Dashboard coverage

- Node overview
- Channels and liquidity
- Payments and fees
- Kubernetes platform
- Security baseline
- Backup and recovery

The security view uses live NetworkPolicy, ServiceAccount, namespace, firing-alert, and telemetry-target data. Falco events and certificate-expiry signals remain explicit Phase 4 inputs and are not represented with fixtures.

## Commands

```sh
ops/verify-monitoring --profile testnet
ops/verify-dashboards
ops/redeploy-check
ops/phase3-acceptance
```

The raw acceptance and redeployment JSON files remain outside Git in `${XDG_STATE_HOME:-$HOME/.local/state}/lnd-ops/evidence/`. The corresponding filenames are `phase3-acceptance-20260924T064834.072613Z.json` and `testnet-redeploy-20260924T064722.304993Z.json`.
