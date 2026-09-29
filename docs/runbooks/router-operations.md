# Testnet Router operational diagnosis

Use kagent's `diagnose_testnet_router` for the fixed `lnd-testnet/lnd-0` node.
It queries existing wallet, LNDmon and backup metrics. It accepts no custom
PromQL, namespace, shell command or action and performs no Kubernetes mutation.

Each signal shows its value, threshold and query time. `observed` means that
sample meets the stated threshold; `attention` means it is below the threshold.
`unknown` means missing, stale, malformed or unavailable evidence. Prometheus
sample timestamps for the metric and its scrape `up` signal must both be newer
than two minutes, and `up` must equal 1. This establishes scrape success, not
node health. Queries run sequentially,
so the results are not an atomic snapshot of the node.

From the Router progress screen, press `o` for monitoring support and choose
current monitoring verification for unknown signals before diagnosing a failure.
The fixed numeric signals and attention runbooks are:

| Signal | Minimum | Runbook |
|---|---:|---|
| `wallet_active` | 1 (SERVER_ACTIVE) | wallet-locked.md |
| `chain_synced` | 1 | chain-sync-stalled.md |
| `connected_peers` | 1 | channel-inactive.md |
| `active_channels_all` | 2 | channel-inactive.md |
| `outbound_demo_sat`, `inbound_demo_sat` | 10,000 sat | liquidity-low.md |
| `backup_current` | 1 (recorded plaintext hash matches current SCB) | scb-backup-stale.md |

These runbooks are available through `get_versioned_runbook`; unknown
monitoring evidence uses lnd-monitoring-unavailable.md. SCB means static channel
backup, and HTLC constraints limit payments that can be held in a channel.
Unlock remains interactive. Existing approved peers may reconnect through the
Router monitor; this diagnosis does not authorize new peer connections, channel
funding, swaps, payments, node restarts or channel closure.

Two active channels in LNDmon can include private channels. Aggregate inbound
and outbound bandwidth above the 10,000 sat demo threshold does not prove a
route with reserves and HTLC constraints. A matching SCB hash does not prove
an external backup copy or successful recovery.

Return to the Router screen for current readiness and separate external P2P and
payer forwarding evidence. This tool never marks Phase 3 complete. An idle node
does not fail just because no recent payment or routing fee was observed.
