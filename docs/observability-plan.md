# Observability plan

This document records the agreed monitoring scope. Metric names and queries must be checked against the pinned LND, lndmon, and Kubernetes component versions during implementation.

## Data sources

- LND's Prometheus exporter: gRPC behavior. Confirm the selected release image has the monitoring feature and that the endpoint works.
- lndmon: chain sync, channel state, liquidity, peers, and wallet data. The pinned v0.2.15 source emits `lnd_chain_synced` and `lnd_graph_synced` (the repository's `metrics.md` lists older `lnd_synced_to_chain` and `lnd_synced_to_graph` names), plus channel inbound/outbound bandwidth, active/inactive channels, pending HTLCs, and peer count.
- Kubernetes: kube-state-metrics for object state; kubelet and node exporter for workload, volume, and host resource usage. Verify the selected K3s and local-path storage combination exposes volume capacity metrics.
- Wallet state: the project collector reads LND's TLS-protected, macaroon-free `/v1/state` endpoint and exposes a fixed one-hot state metric on `/wallet-state`. On the pinned Mac regtest LND image, this returned `NON_EXISTING` before wallet creation. The collector is enabled after manual wallet setup, so live `LOCKED` and `SERVER_ACTIVE` transitions still need verification.
- Host-specific backup jobs: copy each SCB outside its K3s data volume, to the Windows folder or a macOS host folder. Backup freshness monitoring is deferred.
- Logs and events: kagent reads current Pod logs and Kubernetes events. Add long-term log storage only after a runbook needs history that these sources cannot provide.

Sources: [LND configuration](https://github.com/lightningnetwork/lnd/blob/master/sample-lnd.conf), [LND GetState](https://lightning.engineering/api-docs/api/lnd/state/get-state/index.html), [lndmon v0.2.15 chain collector](https://github.com/lightninglabs/lndmon/blob/v0.2.15/collectors/chain_collector.go), [lndmon metrics](https://github.com/lightninglabs/lndmon/blob/v0.2.15/metrics.md), [Kubernetes node metrics](https://kubernetes.io/docs/reference/instrumentation/node-metrics/), [kube-state-metrics](https://github.com/kubernetes/kube-state-metrics).

## Dashboard

Create one Grafana operations overview and three detail views in the first dashboard release: node/channel, payment/liquidity, and Kubernetes.

The initial Git-provisioned dashboard set has all four views. The pinned lndmon source emits aggregate **outgoing** payment outcome and HTLC-attempt counters (`lnd_total_payments`, `lnd_total_htlc_attempts`) plus per-channel inbound/outbound bandwidth. `collector/payment_metrics.py` computes trailing-hour outgoing outcomes, successful-payment fees and observed HTLC resolution latency, plus settled incoming invoice count from paginated LND REST responses. The chart mounts that source from a ConfigMap and runs it on a digest-pinned Python image whose OCI index supports linux/arm64 and linux/amd64. This avoids a privileged node-local image import during deployment. A canceled invoice is not a failed incoming payment, so receive failures remain an explicit gap. Existing panels must be tested with live wallet/channel/payment samples before the dashboard set is accepted.

| Area | Show |
| --- | --- |
| LND readiness | Wallet state, chain and graph sync, best block age, LND and lndmon scrape status |
| Channels and peers | Active/inactive/pending channels, peer count, pending HTLCs, channel capacity |
| Liquidity | Per-channel and aggregate inbound/outbound available balance; ability to send and receive the configured target amount |
| Payments | Aggregate send/receive success and failure counts, latency, and fees; verify the actual collector before defining queries |
| Kubernetes | Node Ready and pressure conditions, Pod readiness/restarts, CPU/memory, LND volume and Linux guest disk free space, Prometheus health |
| Security | Falco event and alert status after sensor compatibility is verified |

Use aggregate payment metrics. Do not add invoice contents, payment hashes, macaroons, or peer identifiers to custom payment metric labels or LLM diagnostic input. Review the labels emitted by upstream exporters before granting access to their raw metrics.

The demonstration target is 10,000 sats for both sending and receiving, adjustable in Helm values. Enable the receive-liquidity alert only after the demonstration has established inbound liquidity; an initially outbound-funded channel can legitimately have no inbound liquidity. Lightning Labs explains the distinct inbound and outbound requirements in its [liquidity guide](https://docs.lightning.engineering/lightning-network-tools/lightning-terminal/channel-liquidity).

Keep Prometheus data for 14 days initially. Monitor Prometheus storage usage and adjust only with evidence.

## Actionable alerts and runbooks

1. **Wallet locked:** tell the operator to unlock it manually. Suppress dependent sync and channel alerts during this state and allow a short startup grace period.
2. **Chain sync stalled:** use lndmon sync state and block age, then inspect Neutrino connectivity, Pod events, and logs. This is the first end-to-end alert and kagent runbook scenario.
3. **Channel inactive:** correlate channel state, peer count, connectivity, and logs. This is the second end-to-end scenario.
4. **LND volume or Linux guest disk low:** distinguish PVC and guest disk pressure before suggesting cleanup. This is the first Kubernetes runbook scenario.
5. **Payment handling:** show failure counts over time, but alert only on consecutive failures or inability to handle the configured send/receive target. Define the consecutive-failure count after observing testnet traffic. Gate the receive-target alert until inbound liquidity has been established and the operator enables it.
6. **Monitoring unavailable:** alert on LND/lndmon scrape failure and on observability Pod failure while Prometheus remains healthy. A stopped Prometheus or PC cannot deliver its own Alertmanager alert in this architecture.

Each alert should carry the affected workload, severity, observed evidence, and runbook reference. kagent first gathers read-only metrics, Kubernetes events, and logs, then proposes the documented action. Low-risk automated actions require their own tested policy. LND restarts, wallet unlocks, and channel, payment, or fund operations require human approval.

The chart now loads chain-sync, inactive-channel, wallet-locked, wallet-state-unavailable, lndmon-unavailable, and payment-collector-unavailable rules in addition to Pod and guest-disk rules. Prometheus reports all eight rules healthy after a Mac monitoring upgrade. `ops/test-lnd-alerts` proved that synthetic chain-sync and inactive-channel metrics reach Alertmanager after the five-minute rule duration. Its `--wallet-locked` mode proved that a synthetic locked state reaches Alertmanager and suppresses dependent alerts even while lndmon serves fault metrics. Both modes clean up their fixture resources. Real wallet lock and unlock transitions and LND fault injection await an unlocked wallet.

Each K3s installation runs its own Prometheus, Alertmanager, and kagent. It cannot alert while its Mac Lima VM, Windows WSL 2 environment, or host is stopped. External availability monitoring is outside this reproducible demonstration scope.

## Later payment extension

First complete direct LND sending, receiving, and liquidity views. Then deploy a small L402-paid API and add request, invoice settlement, and authorization outcomes to the payment detail view. Do not display empty L402 panels before a service produces those events. Lightning Labs describes the flow in its [L402 guide](https://docs.lightning.engineering/the-lightning-network/l402).
