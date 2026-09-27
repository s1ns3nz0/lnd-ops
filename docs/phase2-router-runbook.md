# Phase 3: testnet Router Node

This phase turns the existing persistent `lnd-testnet/lnd-0` identity into a
testnet routing candidate. `lndops` guides wallet unlock, exposure, peer/channel
selection, policy and controlled forwarding checks. It preserves the existing
wallet; channel funding and verification payments require separate amount/fee
approval. The verifier itself is read-only.

## Completion contract

The required contract is all four conditions below. Implementation and real-host
validation are still in progress; see [the current plan](router-always-on-plan.md).

1. LND is synchronized and advertises a public P2P URI.
2. An independent external observer verifies TCP 9735 reaches the expected LND
   identity through NodePort `30973`. RPC, REST, API and metrics remain private.
   A URI alone is not evidence. The standalone observer authenticates the node;
   its execution on a separate network is explicitly attested by the operator.
3. At least two distinct public peers are active, with directional inbound and
   outbound liquidity for the displayed test amount, and the saved policy.
4. A controlled payer-to-receiver payment is matched against payer success,
   receiver settlement and a fresh local forwarding event on the selected
   channel funding points. An old event or direct payment to this node is insufficient.

JSON output separates `ready`, historical `forwarding_proof`, and
`external_reachability`. Historical proof is invalidated for a different wallet or
replaced proof-path channels, but not simply by idle traffic. External reachability
is checked against the current node public key and advertised address on every
poll. With readiness, forwarding evidence and a recent imported observation,
the verifier returns `complete=true`. The external status is `operator_attested`,
not an independently verified network origin. Results expire ten minutes after
request creation. See [observer workflow](../observer/README.md).

## Enable the P2P endpoint

The verifier checks this chart's service contract: `NodePort`, the exact
`app.kubernetes.io/name: lnd-0` selector, and one TCP service port `9735` targeting
numeric port `9735` through node port `30973`. Additional ports, a different
selector, or forwarding to RPC/REST fails the check. Kubernetes defaults for an
omitted protocol or target port are accepted; see [Service defaults](https://kubernetes.io/docs/concepts/services-networking/service/).
This verifies configuration only. It does not inspect EndpointSlices or prove
external connectivity, and it does not audit other services or host listeners.
The external identity-authenticated observation remains a separate requirement.

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

Missing own-channel policy data for any active public channel keeps Phase 3
waiting for graph information, without prompting a policy update. All own-channel
policies must be known and match the target before candidate directions are checked.
During those checks, a missing peer policy does not prevent another usable
direction from proceeding to forwarding verification. If no direction passes and
a candidate reached the missing-peer-policy check, the screen shows graph waiting
instead of the known blockers from other candidates. The pinned LND
`GetChanInfo` response `NotFound: edge not found` also leaves that channel's
policy unknown and keeps its live channel count visible. This does not prove
that synchronization will resolve the missing edge. Other RPC failures,
including Kubernetes NotFound, permissions and connection errors, remain query
errors. This distinction follows the [pinned GetChanInfo implementation](https://github.com/lightningnetwork/lnd/blob/v0.21.3-beta/rpcserver.go).

When policy data is available but no direction passes, the screen identifies
encountered blockers: incoming or outgoing liquidity, amount restrictions in
channel policies, or the configured test fee limit. These describe candidate
directions, not necessarily every channel, and fixing one blocker may reveal
another. Phase 3 keeps checking; it does not send funds or perform swaps to
resolve these conditions automatically.

Phase 3 shows activation confirmations remaining and the earliest funding-expiry
boundary for public pending channels. Multiple known activation counts appear as
a range; missing or malformed values remain unknown, never zero. The values come
from pinned LND's `confirmations_until_active` and `funding_expiry_blocks` fields,
not an estimated time to completion. Zero activation blocks still requires the
channel's actual active state and the remaining Router checks; it does not prove
public gossip propagation. See the [pinned RPC contract](https://github.com/lightningnetwork/lnd/blob/v0.21.3-beta/lnrpc/lightning.proto).

With fewer than two distinct active public peers, any public pending channel at
zero or negative expiry triggers a funding-review message. Another pending channel
may still activate; the message does not mean that all pending funding has failed.
It asks the operator to confirm the affected channel's funding state with its peer,
without refunding, increasing fees or closing a channel. With two distinct active
public peers already present, the expiry row still requests a review of that
pending channel but does not declare the Router unavailable.

From Router progress, `v` displays the independently running monitor's last
heartbeat and node-check age. It reads local records without starting the monitor
or querying Kubernetes. A heartbeat older than 15 seconds or node observation
older than 30 seconds cannot establish current readiness. Future or invalid
timestamps are also unknown. `m` remains the separate service setup action.
The monitor logs `observation_stale` when it first sees no fresh observation, then
one `observation_alert` per continuous stale period, 120 seconds after that first
stale detection. `observation_resumed` means checks resumed, even if
they show a locked wallet; it does not mean the Router recovered. External probe
expiry requests verification again but does not imply a routing outage. These
events are local logs, not configured external notifications.

Open and confirm a second public testnet channel with a reviewed peer. The
interactive `router-channel` helper records the request before funding and blocks
duplicates after an uncertain RPC result. Supply inbound liquidity on one side
and outbound liquidity on another distinct peer for the trial amount. Then apply
the agreed policy explicitly:

```sh
ops/configure-router-policy --confirm "APPLY ROUTER POLICY"
```

The channel wizard separates peer selection, numeric inputs and final approval.
Enter accepts each displayed numeric default: up to 100,000 sat after reserved
and locked balance plus 3,000 sat fee headroom, a 1 sat/vB testnet starting rate,
a fee cap of at least 3,000 sat adjusted for selected inputs, and the current
existing/pending capacity plus the proposed channel amount. These are starting
values, not a confirmation-time guarantee or a promise that the peer accepts
the amount; preflight still checks funds and fees. The final screen requires
uppercase `OPEN`. Enter or `s` cancels with an explicit no-new-request message;
other text prompts again without submitting. Long keys and summaries wrap to
terminal width, and headings use color only on terminals without `NO_COLOR`.

The pinned `lncli openchannel` pending response contains only `funding_txid`;
the journal accepts it without guessing an output index. If no channel point is
saved, reconciliation matches memo, peer, capacity and the complete saved
transaction ID followed by `:`. With a saved point it matches point, peer and capacity.
See [the pinned CLI response](https://github.com/lightningnetwork/lnd/blob/v0.21.3-beta/cmd/commands/cmd_open_channel.go).
Policy updates read each channel's own graph policy first and explicitly pass
its existing `time_lock_delta`, preserving that channel's CLTV setting. Missing
own policy stops the update before any channel is changed. See [the required CLI arguments](https://github.com/lightningnetwork/lnd/blob/v0.21.3-beta/cmd/commands/commands.go).

After a successful funding response, and when revisiting an existing request,
the channel wizard checks the local encrypted SCB with the read-only status
helper. It reports a matching current source, missing backup/record, or an
unverified result. A backup lookup failure does not change the funding result or
permit resubmission. This is a snapshot of the current SCB, not proof that a
pending channel is already included, an external copy exists, or restoration
works. After channel activation, use Router `o` → `5` to check again; use `o` →
`4` to create or refresh the encrypted backup. The automatic lookup neither
creates a backup nor updates its status ConfigMap.

Reconciliation matches the recorded funding point, peer and amount. If the
original response did not provide that point, it requires a unique matching request memo, peer and
amount from an open or pending channel. Opening and closing pending states both
block another submission. For a known funding point, a matching closed-channel
record with a closing transaction and positive close height resolves the request
as `closed`; a new open still needs fresh approval. Abandoned, funding-canceled,
unconfirmed, conflicting or unidentified results remain blocked. Reconciliation
only queries LND and updates the local journal; it never closes or refunds a
channel. A confirmed force close does not imply all timelocked funds are available.

For unresolved requests, the interactive screen shows the memo, peer, amount and
known funding point. Confirm funding status with the peer operator and retry the
status check. Do not delete the journal merely because pending is empty. There
is no manual override that declares an unidentified request safe to resend.

The command saves a wallet-bound target and changes active public channel policies.
Defaults are 1000 msat base, 500 ppm and 1 msat minimum. Maximum HTLC is bounded by
capacity and negotiated pending-HTLC limits, independently of current balances.
Partial RPC failure keeps the target saved; completion requires observed graph
policies to match. It does not pay, fund, or close anything.

The default Phase 3 screen needs only the Router node. It reads that node's
settled forwarding history for the past 24 hours, matching distinct current
public-channel peers and consistent forwarded amounts and fees. It does not
request SSH endpoints or initiate a payment. No traffic means waiting, not a
broken Router; the screen can be closed while LND continues running. A query
examines up to 50,000 events, so the reported count is not an all-time total.
`observed` identifies local LND evidence, distinct from a controlled payment's
`verified` evidence. Neither proves inbound public P2P reachability. Phase
completion still requires current readiness and a fresh external observation;
press `e` to explicitly open its request/import menu when an external network
is available. An idle node may lose the recent observation without losing
readiness. No additional SSH node is required to operate this Router.

For an optional controlled test, `ops/router-proof` prompts for two operator-controlled external peers with direct
public channels to this Router. Existing SSH aliases and remote LND credentials
are used; `PAY` approval bounds the amount and fee. Host clocks must be synchronized.
Response loss triggers reconciliation of the same payment, never a blind resend.
No invoice text or preimage is saved in proof evidence. `ops/testnet-payer route-proof`
uses this helper; its older `pay` mode is a direct-payment exercise. Finally run:

```sh
ops/verify-router
```

Exit `10` identifies outstanding conditions, while `1` means a malformed or
unexpected live result. Exit `0` is reserved for the completed contract; external
verification requires the imported operator-controlled observation, so current readiness alone cannot produce it.

## Support during verification

Use `o` on the Router screen for monitoring or encrypted testnet SCB support,
then return to Router progress. Support does not mark Router complete. Backup
status compares source/ciphertext hashes with the export record and refreshes
the status ConfigMap; seed custody, external copies and isolated recovery remain
separate requirements. Monitoring deployment retains existing LND node count,
Loop/Router flags and public address; adding sidecars can require wallet unlock.

Use `m` to approve installation of the independent monitor. Mac installation is
a login agent; Linux installation starts with Linux/WSL. On Mac, explicitly select
VM startup to start the existing approved project VM before monitoring. Enter
installs monitoring only. Startup checks the saved VM identity/configuration and
allows three attempts, with delays after each command finishes; exhaustion needs
reapproval. Stop the service before manually deleting or recreating that VM.
On WSL, after monitor installation, explicitly select Windows login startup to
register the current Windows user's existing distribution. In the Router screen,
press `m`, install monitoring, then select `y` at the Windows login startup prompt
and enter the displayed confirmation. This needs Windows
Administrator approval and enabled K3s, monitor and forwarding-refresh services.
The task keeps a foreground WSL command attached, retries unexpected exits up to
three times at one-minute intervals, and rejects a changed distribution identity.
It saves no password and runs on battery power. Login-before-use is required;
unattended startup before login and real host-reboot evidence remain outstanding.
Use `ops/windows-router-startup --mode status` to inspect registration and task
state; Running does not prove Router health. Registration failures are not rolled
back automatically. Stop the task before intentionally shutting down WSL, since
an unexpected exit requests recovery. Actual Windows registration/login remains unverified.
To stop it, open Windows **Task Scheduler → Task Scheduler Library**, select the
`LndOps-Router-<distribution GUID>` name shown by status, and choose **End**. Choose
**Disable** as well to prevent the next login from starting it. This does not stop
the distribution or its Router services; intentionally shut down WSL afterward.
Registration checks that the three required Linux services are enabled. If
installation fails, the previous task may already be stopped or replaced: inspect
status, resolve the reported error, and repeat the `m` setup to register it again.
For startup retry exhaustion, inspect the Windows task's last result. For forwarding
failure after WSL starts, inspect `lnd-ops-router-refresh.service` in Linux. These
have separate retry limits; neither proves external P2P reachability.
Actual Mac VM startup and login recovery also remain unverified. The monitor reconnects approved
peers only and never performs funding, swaps or payments automatically.
