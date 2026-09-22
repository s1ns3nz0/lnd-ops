# Observability plan

This document records the agreed monitoring scope. Metric names and queries must be checked against the pinned LND, lndmon, and Kubernetes component versions during implementation.

## Data sources

- LND's Prometheus exporter: gRPC behavior. Confirm the selected release image has the monitoring feature and that the endpoint works.
- lndmon: chain sync, channel state, liquidity, peers, and wallet data. Its documented metrics include `lnd_synced_to_chain`, `lnd_synced_to_graph`, channel inbound/outbound bandwidth, active/inactive channels, pending HTLCs, and peer count.
- Kubernetes: kube-state-metrics for object state; kubelet and node exporter for workload, volume, and host resource usage. Verify the selected K3s and local-path storage combination exposes volume capacity metrics.
- A separate wallet-state check: distinguish a locked wallet from a stalled sync or failed lndmon scrape. Choose its implementation only after testing LND's actual startup behavior.
- WSL host backup job: copy SCB to the Windows folder. Backup freshness monitoring is deferred.
- Logs and events: kagent reads current Pod logs and Kubernetes events. Add long-term log storage only after a runbook needs history that these sources cannot provide.

Sources: [LND configuration](https://github.com/lightningnetwork/lnd/blob/master/sample-lnd.conf), [lndmon metrics](https://github.com/lightninglabs/lndmon/blob/master/metrics.md), [Kubernetes node metrics](https://kubernetes.io/docs/reference/instrumentation/node-metrics/), [kube-state-metrics](https://github.com/kubernetes/kube-state-metrics).

## Dashboard

Create one Grafana operations overview and three detail views in the first dashboard release: node/channel, payment/liquidity, and Kubernetes.

| Area | Show |
| --- | --- |
| LND readiness | Wallet state, chain and graph sync, best block age, LND and lndmon scrape status |
| Channels and peers | Active/inactive/pending channels, peer count, pending HTLCs, channel capacity |
| Liquidity | Per-channel and aggregate inbound/outbound available balance; ability to send and receive the configured target amount |
| Payments | Aggregate send/receive success and failure counts, latency, and fees; verify the actual collector before defining queries |
| Kubernetes | Node Ready and pressure conditions, Pod readiness/restarts, CPU/memory, LND volume and WSL host free space, Prometheus health |
| Security | Falco event and alert status after sensor compatibility is verified |

Use aggregate payment metrics. Do not add invoice contents, payment hashes, macaroons, or peer identifiers to custom payment metric labels or LLM diagnostic input. Review the labels emitted by upstream exporters before granting access to their raw metrics.

The demonstration target is 10,000 sats for both sending and receiving, adjustable in Helm values. Enable the receive-liquidity alert only after the demonstration has established inbound liquidity; an initially outbound-funded channel can legitimately have no inbound liquidity. Lightning Labs explains the distinct inbound and outbound requirements in its [liquidity guide](https://docs.lightning.engineering/lightning-network-tools/lightning-terminal/channel-liquidity).

Keep Prometheus data for 14 days initially. Monitor Prometheus storage usage and adjust only with evidence.

## Actionable alerts and runbooks

1. **Wallet locked:** tell the operator to unlock it manually. Suppress dependent sync and channel alerts during this state and allow a short startup grace period.
2. **Chain sync stalled:** use lndmon sync state and block age, then inspect Neutrino connectivity, Pod events, and logs. This is the first end-to-end alert and kagent runbook scenario.
3. **Channel inactive:** correlate channel state, peer count, connectivity, and logs. This is the second end-to-end scenario.
4. **LND volume or WSL host disk low:** distinguish PVC and host pressure before suggesting cleanup. This is the first Kubernetes runbook scenario.
5. **Payment handling:** show failure counts over time, but alert only on consecutive failures or inability to handle the configured send/receive target. Define the consecutive-failure count after observing testnet traffic. Gate the receive-target alert until inbound liquidity has been established and the operator enables it.
6. **Monitoring unavailable:** alert on LND/lndmon scrape failure and on observability Pod failure while Prometheus remains healthy. A stopped Prometheus or PC cannot deliver its own Alertmanager alert in this architecture.

Each alert should carry the affected workload, severity, observed evidence, and runbook reference. kagent first gathers read-only metrics, Kubernetes events, and logs, then proposes the documented action. Low-risk automated actions require their own tested policy. LND restarts, wallet unlocks, and channel, payment, or fund operations require human approval.

Because Prometheus, Alertmanager, and kagent run on the same PC, they cannot alert while that PC or WSL is stopped. External availability monitoring is outside this reproducible demonstration scope.

## Later payment extension

First complete direct LND sending, receiving, and liquidity views. Then deploy a small L402-paid API and add request, invoice settlement, and authorization outcomes to the payment detail view. Do not display empty L402 panels before a service produces those events. Lightning Labs describes the flow in its [L402 guide](https://docs.lightning.engineering/the-lightning-network/l402).
