# Implementation roadmap

## Goal and deployment contract

The repository must be enough to recreate the same software stack on both machines. On the arm64 Mac, a Lima Linux VM runs K3s. On the Windows 11 Home PC, WSL 2 Ubuntu runs K3s. Both support testnet3/Neutrino and regtest/Bitcoin Core profiles; testnet is a full demonstration target on both, using separate wallets. A prepared host has its Linux guest, systemd, network access, sufficient free disk, and operator privileges available. Enabling Windows features, installing Lima, and funding wallets are manual prerequisites, not tasks for `ops/bootstrap`. Versions, chart dependencies, image digests, configuration, dashboards, and runbooks live in Git. Secrets, wallet seeds, macaroons, live LND data, and SCBs do not.

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

## Phases and reviewable deliverables

| Phase | Work | Exit check |
| --- | --- | --- |
| 0. Reproducible foundation | Pin K3s, Lima, Helm, and initial upstream image versions; write Mac Lima K3s and WSL 2 K3s preflight/bootstrap scripts; enable K3s Secret encryption on both; select a local image load or registry-digest path for each target; add Linux CI for script checks and arm64/amd64 image-manifest inspection. Configure Buildx for any project-built images. | Mac arm64 and Windows amd64 K3s bootstrap successfully; rerunning bootstrap is harmless; the selected images have both platform variants or a tested build path. |
| 1. Small LND slice | Build the project Helm chart for LND with profile-specific testnet3 Neutrino and regtest Bitcoin Core backends, PVC, config, local-only management access, a dedicated token-free ServiceAccount, enforced baseline Pod Security Admission, and default-deny management ingress with explicit operator access. Add `deploy` and `verify` scripts for both hosts and CI chart lint/render for both profiles. Exercise wallet and SCB recovery on regtest with a second LND on each host before using testnet funds. | LND starts on both hosts for testnet and regtest, wallets are manually unlocked, chain sync is observable, CI renders both pinned profiles, regtest recovery passes on both hosts, and a second Helm deployment preserves each node identity and PVC. |
| 2. Core MVP operations | Add lndmon with a read-only macaroon and pinned Prometheus/Grafana/Alertmanager charts, the agreed overview and three detail dashboards, and actionable wallet/sync/channel/Pod/disk alerts. Add host-specific SCB copy jobs and backup inspection commands. Demonstrate separate testnet channels and send/receive flows on both hosts; verify the pinned lndmon payment metrics or add a narrow aggregate collector before claiming the payment panel works. | The end-to-end MVP demonstration and repeat-deploy test pass on both hosts; each SCB copy outside the LND PVC matches the current source file by checksum after a channel change; observations before and after redeploy are recorded. |
| 3. Security proof | Tighten LND Pod Security Admission to restricted where compatible, complete least-privilege RBAC and default-deny egress NetworkPolicy, and test deny cases on both. Install Kyverno in audit mode, fix violations, then enforce the selected policies. Install Falco in its own namespace and verify modern eBPF events on both guest kernels. | Admission, RBAC, traffic-isolation, and Falco event-to-alert tests pass on both hosts. If either kernel prevents Falco collection, document the unmet check. |
| 4. Runbook agent | Attach runbook IDs, evidence queries, and severity to alerts. Connect kagent with read-only Prometheus, events, and log tools first. Test sync-stall, inactive-channel, and disk-pressure diagnosis. Gate LND mutations and funds-related actions on operator approval. | Each injected scenario yields a reproducible diagnosis with evidence and no unauthorized changes. |
| 5. Product extension | Connect Lightning Terminal (`litd`) to the separate LND. Add a small L402-paid API and its request, invoice, and authorization panels. Add Vault for service credentials only if its operational value is demonstrated. | Real L402 requests and payments appear in the integrated dashboard; new components survive repeat deployment without changing the LND wallet. |

Each phase adds its own script checks and Linux container-based validation. A phase is not complete because Helm returned success: its exit check must run against the actual target environment when that environment is available.

## Script interface to implement

- `ops/doctor`: read-only host and cluster preflight, including OS/CPU platform, systemd where needed, disk, ports, cluster version, image-platform availability, and required tools.
- `ops/bootstrap`: create or reconcile Mac Lima K3s or Windows WSL 2 K3s; do not reset an existing cluster.
- `ops/deploy`: install or upgrade pinned charts in dependency order on either target; preserve LND PVC and reject unsafe network/backend changes on an existing wallet.
- `ops/verify`: check Pod, PVC, scrape, dashboard, policy, and LND readiness as each phase becomes available. Report locked wallet as an operator action, not a successful ready state.
- `ops/backup-status`: inspect the SCB copy and most recent successful transfer without printing the backup contents.

Exact implementation language and command syntax will be set with the first vertical slice. Scripts must support noninteractive validation but pause for manual wallet, seed, funding, and channel operations. `helm uninstall`, namespace deletion, PVC deletion, and wallet recreation are never part of ordinary redeployment.

## Open implementation checks

- Confirm the chosen LND image works under the intended Pod Security profile and exposes the expected metrics.
- Confirm every upstream image has both linux/arm64 and linux/amd64 variants; build and run each project-owned image on both targets.
- Verify lndmon's exact payment and liquidity metrics in the pinned version; add a narrowly scoped collector only for missing aggregate signals.
- Verify K3s local-path volume usage metrics and Falco modern eBPF on both guest kernels.
- Confirm a suitable testnet3 Neutrino peer and channel peer before funding.
- Complete the deferred Windows device-encryption and recovery-key check before putting testnet funds in the wallet.

The [operator plan](operator-plan.md) states the product and security decisions; the [observability plan](observability-plan.md) lists the signals and alert/runbook priorities. This roadmap defines delivery order and the MVP boundary.
