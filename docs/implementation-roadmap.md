# Implementation roadmap

## Goal and deployment contract

The repository must be enough to recreate the software stack on a prepared Windows 11 Home PC: clone it inside WSL 2 Ubuntu, run documented scripts, and verify the resulting K3s deployment. "Prepared" means WSL 2 Ubuntu and systemd are available, the machine has network access and sufficient free disk, and the operator can run installation commands with elevated privileges. Windows feature enablement and wallet funding are manual prerequisites, not tasks for `ops/bootstrap`. Versions, chart dependencies, image digests, configuration, dashboards, and runbooks live in Git. Secrets, wallet seed, macaroons, live LND data, and SCBs do not.

"Redeploy" has three distinct meanings:

| Operation | Expected result | Data rule |
| --- | --- | --- |
| Clean bootstrap | Install K3s and create an empty testnet LND deployment | Wallet creation and seed recording are manual gates |
| Repeat deployment | Apply the same pinned charts and configuration again | Preserve the existing LND PVC, wallet, node identity, and channels |
| Disaster recovery | Recover after loss of LND data | Separate manual procedure using the offline seed and SCB; never an implicit `deploy` action |

Scripts must be safe to rerun, check the prerequisites and inputs required for their own operation before changing state, print the actions they take, and never delete a funded PVC. Initial deployment may legitimately start LND with no wallet; a later monitoring installation requires the operator-created read-only macaroon. A redeploy test must compare the node public key, channel list, and PVC identity before and after a second deployment. Ordinary repeat deployment must also preserve Prometheus history; deliberate monitoring-data reset requires a separate documented action.

## MVP completion line

The **core MVP** is complete when a fresh WSL 2 Ubuntu setup can follow the repository's documented bootstrap and deploy commands to reach a testnet3 LND node with persistent data; the operator can manually create and unlock its wallet, open a channel, and make a payment; Grafana shows sync, channel, inbound/outbound liquidity, payment outcome, and basic Kubernetes health; and rerunning deployment preserves the funded node. A local SCB copy must be created and manually inspectable. The operator performs wallet setup, testnet funding, peer choice, and channel or payment operations explicitly.

The MVP does **not** claim automatic recovery, 24-hour availability, or completed security-agent/L402 integration. These remain committed portfolio phases below.

## Phases and reviewable deliverables

| Phase | Work | Exit check |
| --- | --- | --- |
| 0. Reproducible foundation | Pin K3s, Helm, chart, and image versions; write WSL 2 preflight and K3s bootstrap scripts; enable K3s Secret encryption; establish Linux Docker and Mac kind validation; add CI for chart lint/render and script checks. | A clean Ubuntu WSL 2 instance can bootstrap K3s; rerunning bootstrap is harmless; CI renders the same pinned chart inputs. |
| 1. Small LND slice | Build the project Helm chart for testnet3 LND with Neutrino, PVC, config, local-only management access, a dedicated token-free ServiceAccount, enforced baseline Pod Security Admission, and default-deny management ingress with explicit operator access. Add `deploy` and `verify` scripts. Exercise wallet and SCB recovery on regtest with Bitcoin Core and a second LND before using testnet funds. | LND starts, wallet is manually unlocked, chain sync is observable, regtest recovery is demonstrated, and a second Helm deployment preserves node identity and PVC. |
| 2. Core MVP operations | Add lndmon with a read-only macaroon and pinned Prometheus/Grafana/Alertmanager charts, the agreed overview and three detail dashboards, and actionable wallet/sync/channel/Pod/disk alerts. Add the WSL systemd SCB copy job and a backup inspection command. Demonstrate a testnet channel and send/receive flow; verify the pinned lndmon payment metrics or add a narrow aggregate collector before claiming the payment panel works. | The end-to-end MVP demonstration and repeat-deploy test pass; an SCB copy outside the LND PVC at `C:\lnd-ops-backups` matches the current source file by checksum after a channel change; observations before and after the redeploy are recorded. |
| 3. Security proof | Tighten LND Pod Security Admission to restricted where compatible, complete least-privilege RBAC and default-deny egress NetworkPolicy, and test deny cases. Install Kyverno in audit mode, fix violations, then enforce the selected policies. Install Falco in its own namespace and verify modern eBPF events on WSL 2. | Admission, RBAC, traffic-isolation, and Falco event-to-alert tests pass. If the WSL 2 kernel prevents Falco collection, document the unmet check. |
| 4. Runbook agent | Attach runbook IDs, evidence queries, and severity to alerts. Connect kagent with read-only Prometheus, events, and log tools first. Test sync-stall, inactive-channel, and disk-pressure diagnosis. Gate LND mutations and funds-related actions on operator approval. | Each injected scenario yields a reproducible diagnosis with evidence and no unauthorized changes. |
| 5. Product extension | Connect Lightning Terminal (`litd`) to the separate LND. Add a small L402-paid API and its request, invoice, and authorization panels. Add Vault for service credentials only if its operational value is demonstrated. | Real L402 requests and payments appear in the integrated dashboard; new components survive repeat deployment without changing the LND wallet. |

Each phase adds its own script checks and Linux container-based validation. A phase is not complete because Helm returned success: its exit check must run against the actual target environment when that environment is available.

## Script interface to implement

- `ops/doctor`: read-only host and cluster preflight, including WSL 2, systemd, disk, ports, K3s version, and required tools.
- `ops/bootstrap`: install or reconcile the pinned K3s configuration; do not reset an existing cluster.
- `ops/deploy`: install or upgrade pinned charts in dependency order; preserve LND PVC and reject unsafe network/backend changes on an existing wallet.
- `ops/verify`: check Pod, PVC, scrape, dashboard, policy, and LND readiness as each phase becomes available. Report locked wallet as an operator action, not a successful ready state.
- `ops/backup-status`: inspect the SCB copy and most recent successful transfer without printing the backup contents.

Exact implementation language and command syntax will be set with the first vertical slice. Scripts must support noninteractive validation but pause for manual wallet, seed, funding, and channel operations. `helm uninstall`, namespace deletion, PVC deletion, and wallet recreation are never part of ordinary redeployment.

## Open implementation checks

- Confirm the chosen LND image works under the intended Pod Security profile and exposes the expected metrics.
- Verify lndmon's exact payment and liquidity metrics in the pinned version; add a narrowly scoped collector only for missing aggregate signals.
- Verify K3s local-path volume usage metrics and Falco modern eBPF on the actual WSL 2 kernel.
- Confirm a suitable testnet3 Neutrino peer and channel peer before funding.
- Complete the deferred Windows device-encryption and recovery-key check before putting testnet funds in the wallet.

The [operator plan](operator-plan.md) states the product and security decisions; the [observability plan](observability-plan.md) lists the signals and alert/runbook priorities. This roadmap defines delivery order and the MVP boundary.
