# Implementation roadmap

## Goal and deployment contract

The repository must be enough to recreate the same software stack on both machines. On the arm64 Mac, a Lima Linux VM runs K3s. On the Windows 11 Home PC, WSL 2 Ubuntu runs K3s. Both support testnet3/Neutrino and regtest/Bitcoin Core profiles; testnet is a full demonstration target on both, using separate wallets. A prepared Mac has virtualization, Homebrew, network access, sufficient free disk, and operator privileges; `ops/bootstrap` creates the Lima VM if absent. A prepared Windows host has WSL 2 Ubuntu with systemd, network access, sufficient free disk, and operator privileges. Enabling Windows features and installing WSL 2 Ubuntu are host prerequisites; K3s and all project resources are script-created. Wallet creation and funding are manual gates. Versions, chart dependencies, image digests, configuration, dashboards, and runbooks live in Git. Secrets, wallet seeds, macaroons, live LND data, and SCBs do not.

**Primary acceptance test:** on each prepared host, start with no K3s cluster, project namespaces, Helm releases, PVCs, or locally cached project images; the Mac may also start without a Lima VM. Clone the repository and run `ops/doctor`, `ops/bootstrap`, `ops/deploy regtest`, and `ops/deploy testnet` as documented. These commands must create every required Kubernetes resource without hand-created resources or edits to generated manifests. The operator then performs the explicit wallet creation, offline seed recording, read-only macaroon creation, testnet funding, peer/channel choice, and payment steps at their documented gates. Run `ops/verify` after each gate and `ops/redeploy-check` after funding. Run this clean-start test separately on Mac and Windows; a successful upgrade of an existing cluster does not satisfy it.

Use the same project Helm chart with profile-specific values for both targets. Project-built images must produce `linux/arm64` and `linux/amd64` variants from one versioned source revision using Docker Buildx. The image workflow must then make the correct variant available to each K3s cluster, by a pinned registry digest or a documented local load, and test it on both targets. No image publication is required for the initial local build workflow. Before selecting third-party images, verify that their pinned image manifests provide both platforms; a tag or multi-platform build command alone is not a runtime test. Do not copy a funded wallet, seed, channel database, or PVC between the two machines, and never run the same node identity concurrently.

"Redeploy" has three distinct meanings:

| Operation | Expected result | Data rule |
| --- | --- | --- |
| Clean bootstrap | Install K3s and create an empty LND deployment for the selected profile | Wallet creation and seed recording are manual gates |
| Repeat deployment | Apply the same pinned charts and configuration again | Preserve the existing LND PVC, wallet, node identity, and channels |
| Disaster recovery | Recover after loss of LND data | Separate manual procedure using the offline seed and SCB; never an implicit `deploy` action |

Scripts must be safe to rerun, check the prerequisites and inputs required for their own operation before changing state, print the actions they take, and never delete a funded PVC. Initial deployment may legitimately start LND with no wallet; a later monitoring installation requires the operator-created read-only macaroon. A redeploy test must compare the node public key, channel list, and PVC identity before and after a second deployment. Ordinary repeat deployment must also preserve Prometheus history; deliberate monitoring-data reset requires a separate documented action.

## MVP completion line

The **core MVP** is complete when the same pinned chart stack runs as independent testnet3 nodes on Mac Lima K3s and Windows WSL 2 K3s; the operator can manually create and unlock each wallet, open a channel, and make a payment on both; Grafana shows sync, channel, inbound/outbound liquidity, payment outcome, and basic Kubernetes health on both; and rerunning deployment preserves each node's data. Each machine must have a local SCB copy outside its K3s volume. The operator performs wallet setup, testnet funding, peer choice, and channel or payment operations explicitly. Regtest remains the repeatable recovery and integration environment on both machines.

The MVP does **not** claim automatic recovery, 24-hour availability, or completed security-agent/L402 integration. These remain committed portfolio phases below.

## MVP build stages

Each stage leaves a runnable slice on both machines. Do not start testnet funding until the regtest recovery exercise and host encryption check are complete.

| Stage | Deliverable | Both-machine exit check |
| --- | --- | --- |
| 0. Inputs and images | Pin K3s, Lima, Helm, chart dependencies, and OCI images. Define `regtest` and `testnet` values, image distribution, and a Buildx workflow for project images. Add `ops/doctor`. | Preflight identifies each host and CPU; every selected image has a verified arm64/amd64 build or manifest; the load/pull method is documented. |
| 1. Cluster bootstrap | Add host-specific `ops/bootstrap` implementation behind one interface. Install K3s with Secret encryption, persistent local storage, and local-only management access. | Mac Lima K3s and Windows WSL 2 K3s start; images can be loaded or pulled on both; the same bootstrap command can run twice without resetting either cluster or storage. |
| 2. Regtest LND slice | Create the LND and Bitcoin Core Helm resources, a two-node regtest exercise, PVCs, baseline Pod Security Admission, token-free ServiceAccounts, and default-deny management ingress. Add `ops/deploy regtest` and `ops/verify regtest`. Export an SCB for the isolated recovery exercise; host backup automation comes in stage 3. | On each machine: create/unlock two regtest wallets, open a channel, make a payment, rerun deploy without changing node identity, then prove seed+SCB recovery in an isolated recovery exercise. CI renders the regtest chart. |
| 3. Testnet LND slice | Add the Neutrino profile to the same chart and `ops/deploy testnet`; preserve separate testnet PVCs and wallets. Add host-specific SCB copy jobs and `ops/backup-status`. Check host encryption and recovery-key handling before funding. Keep wallet creation, seed recording, funding, peer choice, and payments manual. | On each machine: sync, open an independent testnet channel, make a payment, rerun deploy without changing node key/channel list/PVC, and compare source SCB with its host copy after a channel change. CI renders the testnet chart. |
| 4. Operations view | Install pinned lndmon, Prometheus, Grafana, Alertmanager, and Kubernetes exporters. Provision the overview and three detail dashboards, 14-day retention, wallet/sync/channel/Pod/disk alerts, and the confirmed aggregate payment signal. Make a fresh test payment after monitoring starts. | On each machine: panels show actual chain, channel, liquidity, payment, and Kubernetes changes; a fault injected in regtest reaches Alertmanager; no empty or fabricated metric panel passes. |
| 5. Clean-start and redeploy proof | Add CI checks for chart render, policy syntax, scripts, and both image platforms. Add a clean-host runbook and `ops/redeploy-check` that records node key, channels, PVC UID, SCB checksum, and monitoring history before and after `ops/deploy testnet`. | On each prepared host, scripts build the complete stack from zero Kubernetes resources; the operator completes the documented wallet, seed, macaroon, funding, peer, channel, and payment gates; `ops/verify` passes. `ops/redeploy-check` reruns `ops/deploy testnet` and shows the funded node identity, channels, PVC, SCB copy, and monitoring history remain intact; secret-free evidence is saved. **MVP complete.** |

## After MVP

| Stage | Deliverable | Exit check |
| --- | --- | --- |
| 6. Security proof | Tighten Pod Security Admission to restricted where compatible, complete least-privilege RBAC and default-deny egress NetworkPolicy, then add Kyverno audit-to-enforce rules and Falco. | Admission, RBAC, traffic-isolation, and Falco event-to-alert tests pass on both hosts. Record a kernel incompatibility as an unmet check. |
| 7. Runbook agent | Give kagent read-only access to metrics, events, and logs; connect sync-stall, inactive-channel, and disk-pressure runbooks. Gate LND mutations and funds-related actions on operator approval. | Each injected scenario yields a reproducible diagnosis with evidence and no unauthorized changes on both hosts. |
| 8. Product extension | Connect `litd`, a small L402-paid API, and its request, invoice, and authorization panels. Add Vault for service credentials only if it proves useful. | Real L402 payments appear in the integrated dashboard on both hosts; repeat deployment preserves both LND wallets. |

Each stage adds its own script checks and Linux container-based validation. A stage is complete only after its exit check runs on the target machines; a successful Helm command alone is insufficient.

The regtest checks are deterministic and belong in CI where practical. Testnet checks require faucet funds, a reachable peer, block confirmations, and usable liquidity. Record the node key, channel point, confirmation, payment result, and dashboard observation without secrets on each host. If those external conditions are unavailable, mark the testnet exit check pending rather than treating regtest as equivalent proof.

## Script interface to implement

- `ops/doctor`: read-only host and cluster preflight, including OS/CPU platform, systemd where needed, disk, ports, cluster version, image-platform availability, and required tools.
- `ops/bootstrap`: create or reconcile Mac Lima K3s or Windows WSL 2 K3s; do not reset an existing cluster.
- `ops/deploy regtest|testnet`: install or upgrade pinned charts in dependency order on either target; preserve LND PVC and reject unsafe network/backend changes on an existing wallet.
- `ops/verify`: check Pod, PVC, scrape, dashboard, policy, and LND readiness as each phase becomes available. Report locked wallet as an operator action, not a successful ready state.
- `ops/backup-status`: inspect the SCB copy and most recent successful transfer without printing the backup contents.
- `ops/redeploy-check`: record non-secret node and storage identity, rerun deployment, and compare the result.

Exact implementation language and command syntax will be set with the first vertical slice. Scripts must support noninteractive validation but pause for manual wallet, seed, funding, and channel operations. `helm uninstall`, namespace deletion, PVC deletion, and wallet recreation are never part of ordinary redeployment.

## Open implementation checks

- Confirm the chosen LND image works under the intended Pod Security profile and exposes the expected metrics.
- Confirm every upstream image has both linux/arm64 and linux/amd64 variants; build and run each project-owned image on both targets.
- Verify lndmon's exact payment and liquidity metrics in the pinned version; add a narrowly scoped collector only for missing aggregate signals.
- Verify K3s local-path volume usage metrics and Falco modern eBPF on both guest kernels.
- Confirm a suitable testnet3 Neutrino peer and channel peer before funding.
- Complete the deferred Windows device-encryption and recovery-key check before putting testnet funds in the wallet.

The [operator plan](operator-plan.md) states the product and security decisions; the [observability plan](observability-plan.md) lists the signals and alert/runbook priorities. This roadmap defines delivery order and the MVP boundary.
