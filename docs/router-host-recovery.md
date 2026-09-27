# Router host reboot evidence

In the Router screen, select **o → 6**. Choose **1** before rebooting to save a
baseline, then reboot the host yourself. After logging in, start the existing
VM/WSL if automatic startup is not installed, unlock the existing wallet and
wait for Router readiness. Return to the same menu and choose **2** to verify.
Choose **3** only to abandon the pending baseline; existing successful records
are retained. No menu choice initiates reboot, creates a wallet or stores a password.

Both baseline and final observation require the Router readiness checks to pass.
These include synchronization, two active public channels to different peers,
the configured policy and sufficient directional liquidity for the test amount.
The [Router runbook](phase2-router-runbook.md) defines these checks; a failed
capture prints the current Router reason so that the missing condition is visible.
The Kubernetes API must use a local loopback endpoint. A deliberate SSH tunnel
to a remote cluster is outside this local-host test contract.

The comparison requires the same physical host fingerprint, Kubernetes namespace
and node UIDs, wallet public key, PVC/PV UIDs, and public channel IDs, funding
points and peers. The host must have a new boot identifier and a boot time later
than the baseline. The Kubernetes node's guest boot identifier must also change.
Restarting only a Pod, Lima VM or WSL cannot satisfy the host reboot condition.
The LND Pod must still reference the expected wallet claim and its PV must refer
back to that claim. Balance changes are permitted; channel replacement is not.

Mac observations use the hardware UUID hash and kernel boot session/time.
WSL observations query the Windows host UUID and last boot time through Windows
PowerShell; the WSL boot alone is not the Windows boot. Raw hardware UUIDs and
wallet secrets are not written to evidence. Host clocks must be consistent.
The same host's wall-clock observations must satisfy baseline time < new boot
time <= final observation time. There is no clock-skew allowance; correcting a
clock can require cancelling and preparing a new baseline. These are OS-reported
identifiers, not an independent hardware attestation.

Records are private files in `${XDG_STATE_HOME:-~/.local/state}/lnd-ops/router`.
`host-recovery-pending.json` stores the baseline. A successful verification writes
`host-recovery-mac.json` or `host-recovery-windows.json`, then clears the pending
record. Failures retain the baseline. One recovery lock prevents concurrent
updates, and preparing again cannot silently replace an existing baseline.
The local state directory must survive reboot. There is one latest successful
record per host kind; a later successful test on another Mac replaces the Mac
slot if the same state directory is used. The previous success is not an archive.

The elapsed time starts at baseline capture and includes time before reboot,
startup, manual unlock, waiting and the final check. It is not an outage-duration
measurement or proof of unattended recovery. The report revalidates saved
before/after records, reports the latest successful result for each host kind,
and separately compares the historical wallet/channel set to the current one.
Re-reading historical evidence does not inspect that host's disk again.

External P2P reconnection, address-change recovery and new forwarding remain
separate evidence requirements. Passing this reboot check does not complete Phase 11.
Unit tests cover state transitions; native Mac and Windows reads have been
checked without rebooting. Actual reboot-and-recovery trials remain outstanding.

## Address change recovery

The same **o → 6** menu has **4** to save an address baseline, **5** to verify after
a change, **6** to cancel only that pending baseline, and **7** to create/import an
[external observation](../observer/README.md). Both baseline and final capture
require Router readiness and an unexpired external observation. This is a separate
record from the reboot trial; no action in this menu changes IPs or port forwarding.

First use **7** to collect a fresh external result, then **4** to save the baseline.
After an actual public IP or Kubernetes guest InternalIP change, restore the intended
P2P forwarding and advertised address through the existing configuration workflow.
Use **7** again with a request issued after baseline capture, then **5**. If the
previous ten-minute request is still active, wait for its expiry before issuing a
new one. Never reuse its observation. Clocks must agree. The new request timestamp
must be strictly later than the completed baseline timestamp; requests have
one-second precision, so issue it in a later second.

The collector distinguishes `public_endpoint` from `guest_address` changes. It
requires the same physical host, cluster/node UIDs, wallet, PVC/PV and public
channel set, followed by a fresh successful external observation. Guest IP changes
can preserve the public endpoint, as with WSL forwarding refresh. Public-only
changes do not prove that WSL's internal forwarding refresh was exercised. The
network origin of both observations remains operator-attested, not independently
measured. The collector observes recovery; it cannot prove which action restored it.

Private files `address-recovery-pending.json` and
`address-recovery-{mac,windows}.json` hold the baseline and latest successful result
for each host kind. Failure keeps the baseline; cancellation preserves success.
There is one pending baseline per Router state directory, shared by both host
kinds. Separate machines normally have separate local state directories; collecting
both platforms into a report requires retaining their valid successful records
in the reporting directory. Do not copy wallet credentials or pending baselines.
Elapsed time includes preparation, manual network repair, request expiry waits and
external checking. It is not outage duration or proof of unattended recovery.

The report revalidates these records at their original observation times and
compares their wallet/channel set with the current one. Old observations remain
historical evidence after expiry; current external reachability is checked
separately. Phase 11's report gate requires Pod recovery, Mac and Windows reboot
and address-change histories, ready resources, current Router completion and a
fresh unexpired external check. Automatic startup and actual host trials still
need runtime verification; synthetic tests do not supply those records.
