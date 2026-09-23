# LND chain sync stalled

Trigger: `lnd_chain_synced == 0` for five minutes while the same node's lndmon scrape succeeds. A missing scrape uses the monitoring-unavailable runbook instead. Confirm the affected `namespace` and `service` alert labels before acting.

1. Inspect the node's `Chain synced`, `Best block age`, and `Connected peers` panels. Check Prometheus `up{job="lndmon",namespace="<namespace>",service="<service>"}` and `lnd_chain_synced` for the same labels.
2. Run `kubectl -n <namespace> get pods,events` and `kubectl -n <namespace> exec <service>-0 -- lncli --lnddir=/data/.lnd --network=<regtest|testnet> getinfo`. Compare `synced_to_chain`, block height, peer count, and the Bitcoin backend's height. For regtest, inspect `bitcoin-0` and `bitcoin-cli getblockchaininfo`; for testnet, inspect Neutrino connectivity in LND logs.
3. If the wallet is locked, unlock it interactively. If the Pod is unhealthy or the backend is unreachable, collect redacted logs and events before proposing a restart. Do not restart or unlock a wallet automatically through the runbook agent.

Close the incident when the same node reports `lnd_chain_synced == 1` and the best block age resumes updating. Keep seed, macaroon, invoice, and payment details out of diagnostic notes and LLM input.
