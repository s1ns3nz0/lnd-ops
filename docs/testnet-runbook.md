# Testnet Phase 1 runbook

## Scope

This runbook completes the persistent Windows WSL 2 testnet node used for Phase 1 evidence. Wallet creation, seed custody, faucet use, peer selection, channel funding, and payments are explicit operator actions. The scripts only deploy, inspect, and verify their results.

Run commands from the repository root in WSL. The same flow is repeated later on Mac with a separate wallet.

## Safety rules

- Never paste a seed, wallet password, macaroon, SCB bytes, backup passphrase, recovery key, payment request, or payment hash into Git, issue trackers, chat, logs, or screenshots.
- Record the 24 seed words and wallet password offline and off this PC. The seed alone does not replace the SCB.
- Use only Bitcoin testnet3 coins. Do not send mainnet bitcoin to any address from this runbook.
- Review a faucet, peer operator, address, channel limits, and invoice immediately before use. Do not reuse an address merely because it appears in old documentation.
- Do not uninstall releases or delete the namespace, StatefulSet, PVC, wallet, channel, or SCB during this phase.

## 1. Update and verify the deployment

```sh
git pull --ff-only
ops/doctor
ops/deploy testnet
ops/verify testnet
```

Exit `10` from the final command is expected until the wallet exists and is unlocked.

Use this helper for the remaining non-interactive commands:

```sh
lncli_testnet() {
  kubectl -n lnd-testnet exec lnd-0-0 -c lnd -- \
    lncli --lnddir=/data/.lnd --network=testnet "$@"
}
```

## 2. Create the wallet once

The following command is interactive. Use a new password longer than eight characters. When asked for an existing cipher seed, answer `n` for a new wallet. Record the displayed 24 words offline before confirming that they are saved.

```sh
kubectl -n lnd-testnet exec -it lnd-0-0 -c lnd -- \
  lncli --lnddir=/data/.lnd --network=testnet create
```

Do not run `create` again after success. If the Pod later reports a locked wallet, unlock the existing wallet:

```sh
kubectl -n lnd-testnet exec -it lnd-0-0 -c lnd -- \
  lncli --lnddir=/data/.lnd --network=testnet unlock
```

Verify identity and watch synchronization without recording private material:

```sh
lncli_testnet getinfo
ops/testnet-status
```

`ops/testnet-status` advances one manual gate at a time. While Neutrino is still syncing, leave the Pod running and retry later.

## 3. Fund with testnet coins

Generate a native SegWit testnet address:

```sh
lncli_testnet newaddress p2wkh
```

Review a currently operating Bitcoin testnet3 faucet in a browser, verify that it explicitly supports testnet3, and request at least **250,000 testnet satoshis**. Sharing the generated address is expected; do not share any wallet credential. Keep at least 50,000 satoshis outside the channel for funding fees and later on-chain operations.

Wait for a confirmed balance:

```sh
lncli_testnet walletbalance
ops/testnet-status
```

Do not proceed from an unconfirmed balance.

## 4. Select and connect an external peer

Wait until the public graph has synchronized, then list announced clearnet candidates:

```sh
ops/testnet-peer-candidates
```

The command ranks candidates by visible graph degree; it does not endorse them. Independently verify the selected node's operator, current testnet address, uptime, and channel-size policy through a current operator-controlled source.

Enter the selected `pubkey@host:port` without placing it in shell history:

```sh
read -r -p 'Reviewed testnet peer pubkey@host:port: ' PEER
PEER_PUBKEY=${PEER%%@*}
lncli_testnet connect --perm "$PEER" --timeout 30s
lncli_testnet listpeers
```

Reject the candidate if its pubkey does not match the independently reviewed source or it will not accept the intended channel size.

## 5. Open a public channel

The default Phase 1 target is a 200,000 satoshi public channel with 50,000 satoshis pushed to the remote side. The push creates initial inbound capacity and gives those testnet satoshis to the peer. Increase the amount only when the reviewed peer requires it and the faucet balance leaves the required reserve.

Check the current testnet fee estimate and choose a funding rate no greater than 10 sat/vbyte for this demo. If the network requires more, wait rather than silently exceeding the ceiling.

```sh
CHANNEL_SATS=200000
PUSH_SATS=50000
FEE_SAT_VBYTE=2
lncli_testnet openchannel \
  --node_key "$PEER_PUBKEY" \
  --local_amt "$CHANNEL_SATS" \
  --push_amt "$PUSH_SATS" \
  --sat_per_vbyte "$FEE_SAT_VBYTE" \
  --min_confs 1 \
  --memo phase1-testnet
```

The absence of `--private` is intentional. Wait for the funding transaction to confirm and the channel to become active and public:

```sh
lncli_testnet pendingchannels
lncli_testnet listchannels --public_only --active_only
ops/testnet-status
```

The gate passes only when LND reports a positive-capacity active public channel.

## 6. Enable monitoring and make fresh bidirectional payments

```sh
ops/deploy testnet --monitoring
```

The first monitoring deployment may restart LND. Unlock the existing wallet if requested, wait for the channel to become active, and then create fresh activity so the one-hour monitoring window contains both directions.

For the outgoing payment, obtain a small current testnet BOLT11 invoice from a reviewed external counterparty. Enter it without shell-history exposure, decode it, and confirm that the network, destination, amount, description, and expiry are expected. The Phase 1 invoice should be 10 to 100 testnet satoshis.

```sh
read -r -s -p 'Reviewed testnet BOLT11 invoice: ' OUTGOING_INVOICE; echo
lncli_testnet decodepayreq "$OUTGOING_INVOICE"
lncli_testnet payinvoice --fee_limit 10 --timeout 60s "$OUTGOING_INVOICE"
unset OUTGOING_INVOICE
```

For the incoming direction, create a 10 satoshi invoice and privately give the returned `payment_request` to the reviewed external payer. Do not record the invoice in evidence.

```sh
lncli_testnet addinvoice --amt 10 --memo phase1-incoming --expiry 3600
```

After the payer reports success:

```sh
lncli_testnet listpayments --include_incomplete
lncli_testnet listinvoices
ops/testnet-status
ops/verify-monitoring --profile testnet
```

Both the outgoing success and incoming settlement must be less than one hour old when final acceptance runs.

## 7. Create and verify the encrypted SCB

Run this from an interactive terminal. Use a unique passphrase stored outside this PC. It is independent from the wallet password.

```sh
ops/backup-scb-encrypted testnet lnd-0
ops/backup-status-encrypted testnet lnd-0
```

The encrypted copy is stored at `~/lnd-ops-backups-encrypted/testnet/lnd-0/channel.backup.gpg`, outside the Kubernetes PVC. The status check proves that its recorded plaintext hash equals the live LND SCB hash without decrypting it again.

Create a new encrypted copy after any channel open or close changes the SCB.

## 8. Verify automatic peer reconnection

This check briefly disconnects one active channel peer, waits up to 120 seconds for LND to reconnect automatically, and attempts an explicit restore if automatic reconnection fails.

```sh
ops/testnet-reconnect-check --confirm-peer-disruption
```

Run it only after the channel is active. Do not run it while a payment is in flight.

## 9. Prove state-preserving redeployment

Keep a second terminal ready to unlock the existing wallet if an LND rollout occurs.

```sh
ops/redeploy-check
```

This re-applies the LND and monitoring charts. It must preserve the node key, channel points, LND PVC UID, Prometheus PVC UID, encrypted SCB hashes, cluster identity, and an exact historical Prometheus sample while advancing both Helm revisions.

It writes a private JSON record below `${XDG_STATE_HOME:-$HOME/.local/state}/lnd-ops/evidence/`. Do not commit that raw file.

After a successful run, ensure the final payments are still within the one-hour window. If necessary, make another small outgoing and incoming payment, then run:

```sh
ops/acceptance testnet
```

Exit `0` produces the final private Phase 1 acceptance record. Exit `10` names the remaining manual or freshness gate. Exit `1` means an invariant or evidence contract failed and must not be treated as completion.

## Phase 1 evidence

Create a redacted Markdown record under `docs/evidence/` containing:

- exact public Git commit, date, Windows WSL 2 host, and amd64 architecture;
- `ops/acceptance testnet` pass and private evidence filename/digest;
- public node key, external peer public key, and channel point;
- active/public channel and capacity summary;
- outgoing and incoming success counts and timestamps, without invoices, hashes, or preimages;
- encrypted SCB format, age, and hashes;
- before/after Helm revisions and preserved PVC UIDs;
- Grafana dashboard observations and deferred Windows Device Encryption limitation.

The Phase 1 exit check remains pending until this evidence is generated from the live Windows node.
