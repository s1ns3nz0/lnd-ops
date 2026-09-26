# Phase 2: testnet Router Node

This phase turns the existing persistent `lnd-testnet/lnd-0` identity into a
testnet routing candidate. It never creates a wallet, moves funds, opens or
closes a channel, or makes a payment. The operator supplies the public address,
opens channels, and uses a separate external payer for the forwarding proof.

## Completion contract

`ops/verify-router` is read-only and passes only when all four conditions hold:

1. LND is synchronized and advertises a public P2P URI.
2. TCP 9735 reaches LND through the project-only Kubernetes NodePort `30973`.
   RPC, REST, the Kubernetes API, and metrics remain private.
3. At least two public channels are active, and each has the reviewed policy:
   1 sat base fee, 500 ppm, 1 msat minimum HTLC, and a maximum HTLC below the
   channel's currently local liquidity.
4. LND has recorded at least one forwarding event. A payment directly to this
   node is not a routing proof.

## Enable the P2P endpoint

Choose a stable public DNS name or public IP address, with no scheme or port.
It must resolve to the host that will accept TCP 9735.

```sh
ops/enable-router --external-ip router.example.net
```

The command preserves the existing wallet PVC and configures LND's
`externalip` plus a single NodePort service named `lnd-router-p2p`.

Fresh macOS project VMs receive this Lima forwarding from `ops/lima.yaml.in`.
For an existing VM, add a Lima port-forward from host TCP 9735 to guest TCP
30973, then restart the `lnd-ops-k3s` VM. On Windows, open WSL as administrator
and run `ops/windows-enable-router`; it refreshes the Windows TCP 9735 proxy to
the current WSL address on TCP 30973 and creates the matching inbound Firewall
allow rule. Refresh it after `wsl --shutdown` changes the WSL address.
Do not expose TCP 6443, 8080, 10009, 8989, or 9092.

If the host is behind a home router, cloud firewall, or NAT gateway, allow and
forward only public TCP 9735 there as well. Do not use a management-port rule
as a substitute for this P2P rule.

Confirm from a network outside the host that TCP 9735 is reachable. Then check
that `lncli getinfo` contains the address under `uris` before continuing.

## Channels, policy, and forwarding proof

Open and confirm a second public testnet channel with a reviewed peer. Keep
enough local balance on both channels to forward a small payment. Then apply
the agreed policy explicitly:

```sh
ops/configure-router-policy --confirm "APPLY ROUTER POLICY"
```

The command changes only the active public channel fee policies. It reserves
one satoshi from each local balance and sets the maximum HTLC to the remaining
local liquidity. It does not pay, fund, or close anything.

Use a distinct, external testnet payer to send a small payment whose path can
use this node. The payer and destination must not be this node. Finally run:

```sh
ops/verify-router
```

Exit `0` means the four conditions above are observed. Exit `10` identifies the
next operator action, while `1` means a malformed or unexpected live result.
