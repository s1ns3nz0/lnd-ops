# LND channel inactive

Trigger: `lnd_channels_inactive_total > 0` for five minutes while lndmon is scraped. Confirm the affected `namespace` and `service` labels and whether the channel was expected to be open.

1. Compare `Active channels`, `Inactive channels`, `Connected peers`, and inbound/outbound liquidity panels for the same node. Check chain sync before treating this as a peer problem.
2. Run `kubectl -n <namespace> exec <service>-0 -- lncli --lnddir=/data/.lnd --network=<regtest|testnet> listchannels` and `listpeers`. Record the public channel point and peer public key only. Inspect Pod events and redacted LND logs for connection or funding confirmation failures.
3. Confirm the peer is reachable and the channel is confirmed. Propose a manual reconnect only after the operator reviews the evidence. Channel close, force close, rebalance, payment, and fund operations require operator approval.

Close the incident when the affected channel returns to active state or the operator documents its intentional closure. Do not send raw invoices, macaroons, or payment hashes to the runbook agent.
