# LND monitoring unavailable

Trigger: the wallet-state, lndmon, or payment collector scrape has been down for five minutes. A confirmed `LOCKED` wallet has its own alert and suppresses the dependent lndmon and payment collector alerts. Scrape loss can indicate a Pod, network, TLS, macaroon, or exporter problem.

1. Check the affected Pod's readiness, restarts, and recent events with `kubectl -n <namespace> get pods,events`. Compare wallet-state, LND, lndmon, and payment collector `up` series for the same `service`.
2. Read `lnd_ops_wallet_state` if its scrape is healthy. If it reports `LOCKED`, follow the wallet-locked runbook. Do not place a wallet password in a command argument or automation log.
3. If the wallet-state scrape is down, check the collector's `/wallet-state` endpoint and its TLS connection to LND's `/v1/state`. It needs the LND TLS certificate but no macaroon. If only payment collection is down while the wallet is active, inspect redacted sidecar logs and verify that `readonly.macaroon` exists in the shared mount. Check the monitoring NetworkPolicy and Prometheus target error before changing configuration.

Close the incident when the affected scrape returns to `up == 1` and its expected LND metric series reappear. Never export macaroon bytes, wallet seeds, payment requests, or payment hashes into the alert or LLM context.
