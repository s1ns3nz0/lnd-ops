# Portfolio demo roadmap

## Purpose

This roadmap takes the completed Windows regtest functional MVP to the public portfolio demonstration intended for a Lightning Labs Platform Engineer application. The final deliverable is a reproducible live demo of an operated Lightning platform, with testnet activity, Kubernetes security controls, production-style observability, tested runbooks, and constrained LLM-assisted operations.

The infrastructure recreation contract, wallet-preserving redeployment rules, and Mac/Windows platform requirements remain canonical in [implementation-roadmap.md](implementation-roadmap.md). The signal inventory remains canonical in [observability-plan.md](observability-plan.md), and operational product decisions remain in [operator-plan.md](operator-plan.md). This document defines the post-regtest delivery order and the final demo acceptance line.

## Current baseline

The Windows WSL 2 regtest slice has demonstrated:

- regtest block generation;
- two unlocked LND wallets and peer connectivity;
- one active channel and bidirectional payments;
- live wallet, chain, channel, payment, Kubernetes, and disk monitoring;
- two individually encrypted and verified SCB copies;
- preservation of both node identities, the channel, LND PVCs, SCBs, Prometheus PVC, and historical metrics across chart reapplication.

See [windows-regtest-mvp-2026-09-23.md](evidence/windows-regtest-mvp-2026-09-23.md). Windows Secure Boot and Device Encryption remain a follow-up hardening item; the temporary SCB copies use independent GPG AES-256 encryption.

## How to use this roadmap

This file owns phase order, portfolio scope, and final demo acceptance. The linked implementation, observability, and operator documents own their detailed contracts. If two documents conflict, stop the affected phase, record the conflict as a decision item, update the canonical detailed document first, and then align this roadmap. A phase remains pending until its exit check has fresh host evidence.

| Phase | Status at this revision | Next proof |
| --- | --- | --- |
| Windows regtest functional baseline | Complete | Keep passing during later changes |
| Phase 0 acceptance command | Complete on Windows | Keep the read-only gate passing; repeat on Mac before the final demo |
| Windows testnet | Pending | External peer, channel, payment, backup, and redeploy evidence |
| Mac runtime equivalence | Pending | Host-specific clean and functional evidence |
| Security enforcement | Pending | Positive and negative policy tests |
| Recovery exercise | Pending | Isolated seed-plus-SCB recovery evidence |
| kagent operations | Pending | Read-only diagnosis before any mutation |
| Portfolio demo | Pending | Rehearsed five-minute and reproducibility runs |

Unless a phase defines a stricter value, **recent** means observed within the preceding hour, **current SCB** means its recorded plaintext hash equals the live LND SCB hash, **live data** means a successful scrape from the real workload rather than a fixture, and **reproducible** means the documented commands pass from the clean state defined in `implementation-roadmap.md`. External unavailability such as a faucet, peer, route, Loop service, or registry does not convert a failed test into a pass; record the evidence and leave the affected exit check pending.

## Final completion line

The project is complete when a reviewer can clone the public repository and follow the documented path to watch a live demonstration that proves all of the following:

1. The same pinned stack can be created on Mac arm64 and Windows WSL 2 amd64 without hand-editing generated Kubernetes resources.
2. A persistent testnet LND node connects to external peers, maintains a real channel, and completes a payment.
3. Grafana displays real node, channel, liquidity, payment, Kubernetes, backup, and security data.
4. Kubernetes admission, RBAC, network isolation, and runtime detection controls pass positive and negative tests.
5. An injected operational failure produces a Prometheus alert, selects the matching runbook, and is diagnosed by a read-only kagent workflow.
6. Any automated response stays inside an explicit allowlist and produces an audit record. Wallet secrets, payments, channel closure, SCB deletion, PVC deletion, and policy weakening remain manual actions.
7. Wallet identity, channel state, backups, PVCs, and Prometheus history survive an ordinary repeat deployment.
8. A short, rehearsed demo and a longer reproducibility run both produce secret-free evidence committed to the repository.

## Delivery principles

- Preserve funded wallet PVCs. Clean-start tests use wallet-free disposable environments.
- Keep seeds, wallet passwords, macaroons, SCB bytes, backup passphrases, recovery keys, and kubeconfigs out of Git and demo recordings.
- Use regtest for deterministic integration, fault injection, and recovery exercises. Use testnet for external network and real payment evidence.
- Require a functional exit check for each phase. A successful Helm command alone is not completion.
- Implement operator automation as read-only first. Add narrowly scoped mutations only after the matching runbook and rollback check exist.
- Keep every deployable image digest-pinned and available for linux/arm64 and linux/amd64.

## Phase 0: consolidate the regtest acceptance path

### Deliverables

- Add `ops/acceptance regtest` as the non-secret coordinator for existing verification commands.
- Check wallet readiness, peer/channel state, recent bidirectional payments, both SCB records, live monitoring, and the most recent wallet-preserving redeploy evidence.
- Emit one machine-readable result and one concise terminal summary.
- Remove stale local troubleshooting artifacts and make the README quick path match the tested commands.
- Document the transition from temporary per-file SCB encryption to Windows Device Encryption.

### Initial command contract

`ops/acceptance regtest` will accept no secrets and will not create wallets, payments, channels, backups, or deployments. It will coordinate the existing read-only checks and evidence produced by `ops/verify regtest`, `ops/verify-monitoring --profile regtest`, both SCB status commands, `ops/exercise-regtest` evidence, and `ops/redeploy-check regtest` evidence. The first implementation must define:

- exit `0` for a complete pass, `10` for a missing manual or freshness gate, `1` for a failed invariant, and `2` for invalid invocation;
- a versioned JSON result under the private project state directory plus a concise terminal summary;
- the exact evidence paths, one-hour correlated payment freshness rule, SCB source/hash equality rule, and a successful redeploy result no older than 24 hours;
- timeouts and host-neutral behavior for Mac arm64 and Windows WSL 2 amd64;
- tests that cover a complete pass, a manual gate, stale evidence, mismatched identity/storage state, and malformed evidence.

Troubleshooting artifacts may be removed only from a reviewed explicit inventory. Wallet data, backup data, evidence, PVCs, and operator-created secret material are outside that cleanup scope.

### Exit check

`ops/acceptance regtest` passes on Windows without recreating either wallet and identifies every manual gate precisely when it is absent.

## Phase 1: operate a real testnet node

### Deliverables

- Complete the persistent testnet LND profile and wallet runbook.
- Fund the wallet with testnet coins, connect to a stable external peer, and open a public testnet channel.
- Send and settle at least one real testnet payment.
- Verify chain synchronization, reconnect behavior, channel activity, and a current encrypted SCB.
- Reapply the LND and monitoring charts and compare node identity, channel points, LND PVC, Prometheus PVC, SCB, and historical samples.

### Exit check

A secret-free testnet evidence record proves an external peer, an active public channel, a successful payment, current backup integrity, live dashboards, and state-preserving redeployment on Windows. Repeat the host-specific proof on Mac before the final demo.

## Phase 2: integrate Lightning Labs products

### Delivery order

1. Loop
2. Taproot Assets
3. Pool
4. `litd` as an optional integrated process boundary

### Deliverables

- Add feature flags and separate values for each service.
- Give each component its own ServiceAccount, resource limits, NetworkPolicy rules, and minimum macaroon permissions.
- Add health, failure, request, and liquidity signals to the monitoring stack.
- Start with a testnet Loop quote and probe flow, then perform a small testnet swap when liquidity and external service availability permit.

### Exit check

At least Loop is enabled through versioned Helm values, uses a restricted LND credential, exposes live health metrics, and completes a testnet operation without changing the LND wallet identity during redeployment.

## Phase 3: finish the integrated operations view

### Dashboard set

1. Node overview
2. Channels and liquidity
3. Payments and fees
4. Kubernetes platform
5. Security events
6. Backup and recovery

### Required signals

- wallet and RPC state;
- chain height and synchronization lag;
- peer count and reconnects;
- active, inactive, pending, and force-closing channels;
- local and remote balances, inbound and outbound liquidity, and channel capacity;
- payment and invoice outcomes, HTLC failures, latency, and fees;
- Pod readiness, restart count, resource usage, PVC capacity, disk pressure, and StatefulSet rollout;
- certificate expiry, SCB freshness, policy violations, and Falco events.

### Exit check

Every panel query parses, every required panel shows real regtest or testnet data, and each alert links to a versioned runbook. Empty or fixture-only panels remain visibly pending.

## Phase 4: enforce the Kubernetes security baseline

### Kyverno

- require digest-pinned images;
- require requests and limits;
- require non-root execution and dropped capabilities where compatible;
- deny privileged mode and host namespaces by default;
- restrict hostPath and approved registries;
- require read-only root filesystems where the component supports them.

### RBAC

- use one ServiceAccount per responsibility;
- disable automatic service account token mounts by default;
- grant monitoring read-only discovery;
- give kagent a separate diagnostic role;
- isolate Secret access from general workload inspection.

### NetworkPolicy

- retain default deny;
- permit only documented LND P2P, Bitcoin RPC/ZMQ, monitoring, DNS, and product-specific flows;
- add reviewed egress restrictions after DNS and external testnet dependencies are enumerated.

### Falco and certificates

- detect unexpected shells, processes, sensitive-path access, token access, host namespace use, and suspicious outbound connections;
- route actionable events to Alertmanager and the security dashboard;
- use cert-manager for internal certificates where automatic rotation adds value;
- introduce Vault only for service credentials and wrapped automation keys when its operational cost is justified.

### Exit check

Allowed workloads continue to operate. Purpose-built violating fixtures are rejected by Kyverno, denied by RBAC or NetworkPolicy, or detected by Falco as appropriate. Each result is captured without weakening a production policy for the test.

## Phase 5: make backup and recovery operational

### Deliverables

- Enable Secure Boot and Windows Device Encryption, record the recovery key outside the host, and replace temporary encrypted-file SCBs with the standard protected-volume copies.
- Automate SCB freshness and integrity reporting without exposing backup bytes.
- Keep each node's seed and SCB independent.
- Exercise seed-plus-SCB recovery in an isolated namespace.
- Prevent the original and recovered copies of one identity from running concurrently.

### Exit check

The recovery exercise proves the documented LND data-loss-protection outcome, backup freshness alerts work, and the ordinary active-channel demo still uses the original preserved wallet PVC.

## Phase 6: validate alerts and runbooks with faults

### Scenarios

- locked wallet;
- unavailable Bitcoin backend;
- chain-sync delay;
- loss of all peers;
- inactive channel;
- payment failure increase;
- exhausted inbound or outbound liquidity;
- low PVC capacity or disk pressure;
- failed collector scrape;
- expiring certificate;
- suspicious runtime activity detected by Falco;
- Pod crash loop.

### Required flow

For each selected scenario, record:

```text
fault injection -> metric or event -> alert -> runbook -> recovery -> post-check
```

### Exit check

At least one Lightning failure, one Kubernetes failure, and one security event traverse the entire flow and return to a verified healthy state.

## Phase 7: add kagent runbook operations

### Read-only stage

Allow kagent to inspect only:

- Pod, StatefulSet, PVC, and event status;
- redacted workload logs;
- Prometheus alerts and approved queries;
- Falco events;
- versioned runbooks;
- non-secret LND status exposed through a restricted diagnostic interface.

The response must contain the observed facts, likely cause, confidence, matching runbook, recommended command, and whether the action is eligible for automation.

### Restricted response stage

Initial allowlisted actions may include:

- restarting a stateless collector or monitoring Deployment;
- rerunning a scrape or health verification;
- creating a redacted diagnostic bundle;
- attaching a runbook link and evidence to an alert.

The agent must not create or unlock wallets, handle seeds, initiate payments, close channels, delete SCBs or PVCs, recreate the cluster, or relax security policy.

### Exit check

Injected scenarios produce reproducible diagnoses grounded in live evidence. An allowed response succeeds with an audit record, a forbidden response is denied, and a cooldown prevents repeated mutation loops.

## Phase 8: complete reproducibility and CI

### Stable command surface

```sh
ops/doctor
ops/bootstrap
ops/deploy regtest
ops/deploy testnet
ops/deploy-monitoring
ops/deploy-security
ops/acceptance regtest
ops/acceptance testnet
```

### CI gates

- Bash and Python checks;
- Helm lint and rendering;
- Kubernetes schema validation;
- Kyverno policy tests;
- RBAC and NetworkPolicy negative tests;
- secret scanning;
- dependency and image vulnerability scanning;
- arm64 and amd64 image-manifest checks;
- collector unit tests;
- dashboard and PromQL checks;
- runbook and alert-link validation.

### Exit check

The documented clean path works on Mac arm64 and Windows WSL 2 amd64. CI covers platform-independent checks on Linux, and host evidence covers the runtime behavior CI cannot reproduce.

## Phase 9: produce the portfolio demo

### Demo artifacts

- architecture and trust-boundary diagrams;
- concise threat model and security decisions;
- live Grafana dashboards;
- one failure injection and alert demonstration;
- one kagent diagnosis and one allowlisted response;
- wallet-preserving redeployment proof;
- backup/recovery evidence;
- clean-start evidence for both platforms;
- known limitations and next-step document;
- a five-minute demo script and a longer reproducibility guide.

### Five-minute demo sequence

1. Show the pinned architecture and two supported host platforms.
2. Show a healthy testnet LND node, external peer, active channel, and liquidity dashboard.
3. Complete or display a recent successful payment and its metrics.
4. Inject one safe regtest fault and show the alert.
5. Ask kagent for a runbook-grounded diagnosis and execute one allowlisted response.
6. Reapply the charts and show identity, channel, PVC, SCB, and Prometheus continuity evidence.
7. Close with the security controls, recovery boundary, and known limitations.

### Final demo acceptance

The demo passes only when it can be repeated from the documented repository revision, finishes without exposing secrets, uses live data for every claimed behavior, and leaves both funded wallets and channels intact. Record the exact commit, host, commands, screenshots or terminal evidence, results, and deferred limitations.

## Recommended execution order

| Order | Phase | Main outcome |
| ---: | --- | --- |
| 1 | Phase 0 | One regtest acceptance command |
| 2 | Phase 1 | Real Windows testnet node and payment |
| 3 | Phase 3 | Live integrated dashboards and alerts |
| 4 | Phase 4 | Enforced Kubernetes security controls |
| 5 | Phase 5 | Protected backup and recovery exercise |
| 6 | Phase 6 | Fault-to-runbook proof |
| 7 | Phase 7 | Constrained kagent diagnosis and response |
| 8 | Phase 2 | Loop and selected Lightning Labs extensions |
| 9 | Phase 8 | Both-host reproducibility and CI |
| 10 | Phase 9 | Rehearsed public portfolio demo |

The immediate next implementation slice is Phase 1: finish the Windows testnet runbook and verification tools, then pass the external peer, public channel, payment, encrypted backup, monitoring, and state-preserving redeployment gates. The working sequence is maintained in [demo-execution-plan.md](demo-execution-plan.md).
