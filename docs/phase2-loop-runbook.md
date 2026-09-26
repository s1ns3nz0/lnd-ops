# Phase 2: Loop runbook

This optional testnet-only slice runs Lightning Loop beside the existing LND
node. Loop uses submarine swaps to move value between a Lightning channel and
on-chain Bitcoin without closing the channel. It is disabled by default and no
repository command creates a swap, pays an invoice, or changes channel state.

Both supported hosts use the same commands: macOS through Lima K3s and Windows
through WSL 2 K3s. The Loop image is pinned to an OCI index that contains both
`linux/arm64` and `linux/amd64` variants.

## Credential boundary

`loopd` never mounts the LND PVC. Before enabling it, create a
**custom-baked macaroon** containing the Loop-required LND RPC permissions;
do not supply `admin.macaroon`. The Loop configuration accepts a custom
macaroon, but it must contain every permission needed by Loop's enabled
subservers. Keep the result in a private, mode-`0600` host file; do not add it
to Git, a transcript, or evidence.

The operator gives its file path to `ops/enable-loop`. The command copies the
current LND TLS certificate directly from the Pod into the owner-controlled
Kubernetes Secret `lnd-loop-credentials`, without printing either credential.
It first performs an ordinary monitoring deployment so LND refreshes the
certificate with the in-cluster `lnd-0` service name. Ordinary redeployment
preserves the funded wallet PVC.

```sh
chmod 600 /secure/path/loop.macaroon
ops/enable-loop --macaroon /secure/path/loop.macaroon
ops/verify-loop
```

`ops/verify-loop` checks the Loop health endpoint and requests a 10,000-sat
testnet Loop Out quote. A quote is read-only: it does not initiate a swap.
It runs both checks inside `lnd-testnet/deployment/loopd`: the `loop-health`
container serves `http://127.0.0.1:9094/metrics`, and the `loopd` container
executes the quote using its local `/loop` state. The LND credential Secret
must contain exactly `loop.macaroon` and `tls.cert`; it is mounted read-only at
`/credentials`. Loop's own state and macaroon stay in the separate `loop-data`
PVC, mounted at `/loop`.

| Exit | Meaning |
| --- | --- |
| `0` | The local authenticated health check and quote both succeeded. |
| `10` | Loop is not enabled, LND must be unlocked, or Loop is still starting. |
| `1` | A deployed Loop API or quote check failed. |
| `2` | Invalid `ops/enable-loop` invocation or insecure macaroon file mode. |

`ops/enable-loop` creates or updates the Secret idempotently, uses an owner-only
temporary directory for the certificate, and removes it on exit. It restarts
`loopd` after replacing the Secret, so a refreshed LND certificate is loaded.

## Controls and observability

- `loop.enabled` defaults to `false` in Helm values.
- The Loop ServiceAccount has no Kubernetes API token or RBAC permissions.
- NetworkPolicy permits only DNS, Loop-to-LND RPC on TCP 10009, the public Loop
  service on TCP 11010, and Prometheus scraping of the health endpoint on TCP
  9094.
- `lnd_ops_loop_healthy` reports whether Loop's local authenticated API works.
  `lnd_ops_loop_swaps_total` contains only aggregate state counts and no
  payment request, payment hash, macaroon, address, or peer label.
- `maxL402Cost` and `maxL402Fee` both default to zero. A real testnet swap is a
  separate manual, fund-moving action and requires explicit operator approval.

To disable Loop while retaining its state for inspection, reapply the ordinary
testnet chart without `--loop`:

```sh
ops/deploy testnet --monitoring --no-loop
```

The next implementation proof is a separately approved small testnet swap,
followed by a wallet-preserving redeploy and secret-free evidence. An external
Loop service or testnet-liquidity failure leaves that proof pending.
