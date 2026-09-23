# LND wallet locked

The `LndOpsWalletLocked` alert means the read-only state endpoint reported `LOCKED` for at least two minutes. The node is present but needs an operator to unlock its wallet. Payment and lndmon scrape failures are suppressed while this state is reported.

1. Check `lnd_ops_wallet_state{state="LOCKED"}` and `up{job="lnd-wallet-state"}` for the affected namespace and Service. If the state scrape is down, use the monitoring-unavailable runbook instead.
2. Inspect the LND Pod phase, restarts, and recent events. Confirm that the PVC is still Bound and the Pod is using the expected profile.
3. Ask the operator to run `lncli --lnddir=/data/.lnd --network=<regtest|testnet> unlock` interactively inside the affected Pod. Do not paste a password into a shell argument, log, ticket, dashboard, or agent prompt.
4. Confirm `lnd_ops_wallet_state{state="SERVER_ACTIVE"} == 1`, then verify lndmon and payment collector scrapes and chain sync. A brief `UNLOCKED` or `RPC_ACTIVE` state during startup is normal.

Never delete the PVC, restore a seed, restart LND, or open a channel automatically in response to this alert. Escalate if the wallet does not become active after the operator unlocks it.
