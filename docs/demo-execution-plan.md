# Demo execution plan

## Goal

The finish line is a repeatable portfolio demonstration for a Lightning Labs Platform Engineer application. A reviewer must be able to clone one public revision, create the stack on Windows WSL 2 amd64 or Mac arm64, and see a real testnet Lightning node, live operations data, enforced Kubernetes security controls, and a runbook-grounded kagent diagnosis without exposing wallet secrets.

The detailed phase scope remains canonical in [portfolio-demo-roadmap.md](portfolio-demo-roadmap.md). This document is the working checklist from the current repository state to the demo. It controls delivery order and phase gates; linked runbooks own copy-and-run commands and platform prerequisites. If the documents disagree, stop the affected phase, update the detailed canonical document, and then align this checklist before continuing.

Each host runs an independent wallet. Reproducibility means creating an equivalent stack and passing the same functional gates; it does not mean cloning an existing wallet, channel, or payment history. External funding, peer, routing, and counterparty steps are declared manual gates and cannot be reproduced from source code alone.

## Current position

Status updated on 2026-09-24. Every evidence record pins the exact Git commit used, so this status does not substitute for revision-specific evidence.

- **Complete:** scripted K3s and Helm deployment on Windows WSL 2; disposable two-node regtest; wallets, channel, bidirectional payments, monitoring, encrypted SCBs, and state-preserving chart reapplication.
- **Complete:** `ops/acceptance regtest` and secret-free Windows Phase 0 evidence.
- **Complete:** persistent Windows testnet node. The wallet is funded and synchronized, its external peer and public channel are active, real outgoing and incoming payments succeeded, monitoring observed both directions, a Pod restart preserved the node identity and restored the public channel peer, and chart reapplication preserved the wallet, channels, SCB, PVCs, and Prometheus history. `ops/acceptance testnet` passed on runtime revision `c1312c94c1ba1d3b098d7582b4d872f5324aa2ae`; the secret-free Phase 1 record documents that run.
- **Complete:** Windows Phase 3 integrated operations view. Six dashboards returned live data for all 54 panels, all 14 alert rules were healthy with versioned runbooks, the current encrypted SCB was visible, and chart reapplication preserved the funded node and Prometheus history. `ops/phase3-acceptance` passed on runtime revision `14487d13682417bcaf920e9df5163907e3197bfa`.
- **Complete:** Windows Phase 4 Kubernetes security baseline. Enforced Kyverno admission, scoped RBAC, default-deny NetworkPolicy, a real modern eBPF Falco event through Alertmanager, live LND certificate expiry, 57 live dashboard queries, 16 healthy alert rules, and Phase 3 continuity passed on runtime revision `0f13cc8463ef0c3aee9738fc43f1541f628360cc`.
- **Deferred hardening:** Windows Secure Boot and Device Encryption. Until those are enabled, testnet SCBs use independent GPG encryption and the limitation must appear in demo evidence.

## Delivery order

| Step | Outcome | Completion proof |
| ---: | --- | --- |
| 1 | Windows testnet operation | Synced wallet, confirmed testnet balance, reviewed external peer, active public channel, outgoing payment, settled incoming invoice |
| 2 | Testnet backup and redeployment | Current encrypted SCB; node identity, channel, LND PVC, Prometheus PVC, and historical sample survive chart reapplication |
| 3 | Operations dashboards | Live node, chain, channel, liquidity, payment, Kubernetes, backup, and security views; alerts link to runbooks |
| 4 | Kubernetes security baseline | Kyverno, scoped RBAC, default-deny NetworkPolicy, Falco, and certificate handling pass positive and negative checks |
| 5 | Recovery and fault exercises | Isolated seed-plus-SCB recovery plus one Lightning, one Kubernetes, and one security fault traversing alert to recovery |
| 6 | kagent operations | Read-only diagnosis from live evidence; one allowlisted response succeeds and one forbidden response is denied with audit evidence |
| 7 | Lightning Labs product slice | Loop is deployed with restricted credentials, metrics, and one testnet operation; other products remain explicit extensions |
| 8 | Mac equivalence and clean reproduction | Same pinned stack and functional gates pass on Mac arm64; both hosts pass the documented clean-start path |
| 9 | Portfolio demo | Five-minute presentation and longer reproduction run pass from the recorded public commit without secret exposure |

## Step 1: finish the Windows testnet node

Operator actions involving secrets, funds, peer selection, or payments remain manual. Scripts may inspect and verify their results.

1. Create the testnet wallet interactively and record its seed and password outside Git, logs, screenshots, and the host alone.
2. Unlock the wallet and wait for Neutrino chain synchronization.
3. Generate a testnet on-chain address, obtain testnet coins from a currently reviewed faucet, and wait for confirmation.
4. Inspect candidates from the live public graph, independently review the operator and address, and connect to one external peer.
5. Open a public channel with a conservative testnet amount and wait until it is active.
6. Decode and pay a reviewed testnet BOLT11 invoice.
7. Create a small invoice and have an external testnet payer settle it.
8. Verify peer reconnect behavior without closing the channel.
9. Run the testnet progress and monitoring gates.

No old faucet or peer address is treated as permanent configuration. External dependencies must be reviewed at execution time. A peer, faucet, route, or payer failure leaves the gate pending; select and record a newly reviewed alternative rather than weakening the check.

The exact interactive commands, numeric channel amount, fee ceiling, confirmation requirement, reconnect timeout, and evidence fields belong in `docs/testnet-runbook.md`. That runbook and its read-only verification command must exist before testnet coins are committed to a channel.

### Phase 1 exit condition

A secret-free Windows evidence record must prove all of the following:

- the node is synchronized and has a stable identity;
- at least one reviewed external peer is connected;
- at least one positive-capacity public channel is active;
- at least one outgoing payment succeeded and one incoming invoice settled;
- Grafana and Prometheus show live node, liquidity, payment, and Kubernetes data;
- the encrypted SCB record matches the live LND SCB plaintext hash;
- ordinary chart reapplication preserves identity, channel points, both PVCs, and a historical Prometheus sample.

## Step 2: prove backup and redeployment

1. Create and verify the encrypted testnet SCB outside the Kubernetes volume.
2. Run the read-only acceptance checks before changing the release.
3. Reapply LND and monitoring charts through the repository scripts.
4. Unlock the wallet if the restarted LND process requests it.
5. Compare the before and after identity, channels, PVC UIDs, SCB hashes, Helm revisions, and exact Prometheus sample.
6. Commit only the redacted Markdown evidence. Keep raw JSON evidence in the protected project state directory.

Deleting namespaces, releases, PVCs, wallets, or channels is not part of this proof.

Here, ordinary chart reapplication means the repository's Helm install-or-upgrade path against the existing releases and claims. It must advance the expected Helm revisions without uninstalling a release or replacing a PVC. The redeployment verifier selects and records one pre-change Prometheus series, timestamp, and value, then proves the same sample remains queryable afterward.

## Steps 3 through 7: production-style operations

Implement these as vertical slices. Each slice includes configuration, observable signals, an alert, a runbook, a positive check, a negative or failure check, and secret-free evidence.

1. Finish the integrated dashboards and alerts.
2. Enforce Kyverno, RBAC, and NetworkPolicy controls, then add Falco runtime detection.
3. Exercise isolated recovery and representative operational faults on regtest.
4. Give kagent read-only access to approved Kubernetes, Prometheus, Falco, runbook, and redacted LND diagnostic data.
5. Add a very small mutation allowlist with audit records and cooldowns.
6. Add Loop as the first Lightning Labs product integration with restricted credentials and its own metrics.

Wallet creation or unlock, seed access, payment initiation, channel closure, backup deletion, PVC deletion, and security-policy weakening stay outside kagent automation.

The Step 3 cluster-read-only gate is `ops/phase3-acceptance`. Run it from a clean checkout with the intended `KUBECONFIG`; it preserves the Phase 1 testnet gate, requires a current encrypted SCB, executes every PromQL expression in the six Git-provisioned dashboards against live Prometheus data, and verifies every required alert and runbook link. It writes a private `0600` summary under the project state directory, including the Git commit, Kubernetes context, proof-command mapping, and explicit Phase 4 exclusions. Exit `0` is a pass, `10` identifies a required operator action, `1` is a failed invariant, and `2` is invalid invocation. Falco and certificate-expiry panels enter this gate after their Phase 4 producers exist.

## Step 8: Mac equivalence and reproducibility

Run the same versioned scripts on Mac arm64 with a separate wallet and separate testnet channel. Record both forms of proof:

1. **Clean infrastructure proof:** from a prepared host with no project Kubernetes resources, the documented commands create the cluster, namespaces, charts, monitoring, and security resources without editing generated manifests.
2. **State preservation proof:** after the one-time manual wallet and funding gates, repeat deployment preserves the wallet identity, channel state, backups, PVCs, and monitoring history.

CI covers vendor-neutral linting, rendering, policy tests, script tests, secret scanning, and multi-architecture image manifests. Host evidence covers behavior that CI cannot reproduce.

## Step 9: final demo acceptance

The five-minute presentation combines live status with recent, commit-linked evidence for operations that are unsafe or too slow to repeat on stage. It must show, in order:

1. the architecture, trust boundaries, pinned versions, and two supported host platforms;
2. the live testnet node, external peer, public channel, and inbound/outbound liquidity;
3. a recent successful payment and matching metrics;
4. one safe regtest fault, the alert, and its linked runbook;
5. kagent producing a grounded diagnosis and one audited allowlisted response;
6. identity, channel, PVC, SCB, and Prometheus continuity after chart reapplication;
7. the enforced security controls, recovery result, and explicitly deferred limitations.

The live portions are node/channel status, dashboards, one recent payment view, one safe regtest fault, and the kagent diagnosis. Cross-platform clean creation, recovery, security negative tests, and redeployment continuity may use evidence produced during the final rehearsal. That evidence must be no older than seven days unless a stricter phase rule applies.

The demo is complete only when the documented public commit has passed on both target platforms, every claimed behavior uses either current live data or qualifying rehearsal evidence, secret scans and a recording review pass, and funded wallets and channels remain intact.

## Evidence rule

Every completed step records the repository commit, date, host and architecture, commands, redacted results, and limitations under `docs/evidence/`. Node pubkeys and channel points may be included as public testnet identifiers; seeds, wallet passwords, macaroons, SCB bytes, backup passphrases, recovery keys, kubeconfigs, payment requests, and raw payment hashes must not be committed or recorded. A Helm success message by itself is not proof. An unavailable faucet, peer, route, registry, or external Lightning service leaves the affected check pending.

Raw machine-readable evidence stays under `${XDG_STATE_HOME:-$HOME/.local/state}/lnd-ops/evidence/` with owner-only permissions. It remains outside Git. Before publishing, run the repository secret scan and review the screen recording once from start to finish.

## Immediate next action

Proceed to Phase 6 fault-to-runbook exercises. Keep `ops/phase5-acceptance`
passing after changes that affect LND, monitoring, storage, networking,
recovery, or security, and repeat the host-specific testnet, operations,
security, and recovery proof on Mac during the cross-platform phase.

The Windows Phase 6 rehearsal command is `ops/exercise-phase6-faults`. It uses
one active disposable regtest channel and the live monitoring/security stack.
It restores NetworkPolicy in a `finally` path, deletes only its named
CrashLoop Pod, and lets the Falco rolling event window expire. Do not interrupt
the command while a fault is active; if the process is interrupted, restore the
Git-rendered `lnd-peer-traffic` policy and delete Pod `phase6-crashloop` before
continuing. A successful run writes owner-only evidence, after which
`ops/phase6-acceptance --acknowledge-host-encryption-deferred` reruns Phase 5
continuity.
