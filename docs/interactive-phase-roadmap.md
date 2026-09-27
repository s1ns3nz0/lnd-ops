# Interactive Phase Runner Roadmap

`lndops` should keep one Phase on screen until its completion verifier passes.
Each Phase follows the same contract: show a compact live status, collect only
the input needed for the next action, perform that action, and immediately
recheck. The command prompt returns only after the selected Phase is complete
or the operator explicitly interrupts it.

## Implemented runner contract

The runner now assigns every Phase a stable internal ID, a read-only completion
probe, and an interactive route. Phase 1 checks regtest wallets, channels,
and payments. Phase 2 checks the testnet wallet, synchronization and peers.
Phase 3 keeps its Router screen active and patches compact rows rather than
appending polling logs. The timer updates independently of its RPC worker.
Phase 4 is optional; cumulative builds for later phases skip it. Selecting 4
explicitly still runs its setup and quote verification. Phase 5 verifies live
testnet metrics without requiring recent personal payments. Phase 6 through 11 use their existing
acceptance evidence as the completion contract, and invoke their existing
interactive scripts only after their own confirmation prompt.

## Phase 1 · regtest foundation

**Implemented:** existing wallets are detected, unlock/create helpers and the
channel/payment exercise run interactively. Real host evidence remains separate.

**Change:** detect whether the selected regtest workspace already has both
wallets. For an existing workspace, unlock both wallets interactively. For a
new workspace, ask once before creating each wallet, show the seed custody
checkpoint, then create the local channel and run the bidirectional payment
exercise. Recheck the regtest verifier after every action.

## Phase 2 · persistent testnet node

**Implemented:** wallet unlock, synchronization and peer readiness. Private
send/receive activity and Router channel setup are not Phase 2 requirements.

**Change:** retain the existing unlock flow, then display the next missing
testnet condition only: wallet unlock, chain/graph sync or peer connection.
Poll automatic conditions and recheck after
each operator-confirmed condition.

## Phase 3 · testnet Router Node

**Current gap:** external reachability evidence and real host recovery remain
unverified. This phase is not complete merely because its UI is implemented.

**Change:** keep the Router progress screen active through chain/graph sync,
public URI, distinct public peers, directional liquidity, policy application,
and external forwarding. Channel opens and controlled external payments show
amounts and require explicit approval; uncertain submissions are not resent.
Readiness, dated historical forwarding evidence and external reachability are
displayed separately. Missing external SSH access does not erase earlier evidence.

`o` opens observability and backup support while Phase 3 remains pending.
It can deploy monitoring, enable collectors, verify metrics, export an encrypted
testnet SCB, or compare the current SCB/ciphertext hashes with the saved backup record.
The backup-status helper also updates the existing status ConfigMap; it does not
decrypt again or prove recovery readiness. Seed custody and an external backup
copy remain separate requirements. Failed actions remain in the support menu;
cancelled actions return to Router progress with a fresh query. No support action
marks Router complete or advances cumulative phases.

Monitoring redeploy preserves the existing LND node count and the existing
monitoring/Loop/Router flags and Router address. Every configured node must have
its read-only macaroon and unlocked RPC before the upgrade. Other Helm customization
preservation is not established by this change. Pod replacement may require unlock.

## Phase 4 · Loop liquidity management

**Current gap:** Loop is only described even though a read-only quote verifier
already exists.

**Change:** when explicitly selected, prompt for the local path of the dedicated Loop macaroon, validate
that it is readable without echoing it, deploy Loop, wait for its workload,
then run the health and read-only quote verifier. Never offer a swap in this
runner.

## Phase 5 · observability

**Current gap:** the runner verifies only monitoring infrastructure, so it can
finish before it sees live LND metrics and payment history.

**Change:** deploy the shared monitoring stack when absent, unlock the selected
wallet when required, wait for collector targets to become healthy, and verify
the selected profile rather than infrastructure alone. Zero recent payment count
is valid for a routing-only testnet node; absent metrics or failed scrapes are not.

## Phase 6 · security baseline

**Current gap:** deployment is automatic but completion remains a generic
manual instruction.

**Change:** deploy Kyverno and Falco, wait for their workloads, run the
read-only security verifier, then create Phase 6 acceptance evidence only
after it passes. Report the failing policy or runtime signal in plain language.

## Phase 7 · backup and recovery

**Implemented:** the runner exposes encrypted backup, external encrypted-copy
verification and isolated regtest recovery actions. Acceptance requires the
external copy to match the current SCB; missing or stale copies cannot complete
the Phase. Real external-copy verification and isolated recovery evidence are
required for completion; source tests do not supply them.

**Change:** show backup freshness and encrypted SCB status first. Require an
explicit per-step confirmation before any recovery rehearsal that can change a
wallet or PVC. Keep the recovery run isolated, collect its evidence, restore
the original environment, and verify the acceptance gate before completion.

## Phase 8 · fault and alert exercise

**Current gap:** the runner only points at the fault exercise.

**Change:** show the three reversible fault classes, require a confirmation
immediately before injection, stream concise exercise progress, confirm every
resource has been restored, then run the acceptance verifier. No next Phase is
available while restoration is incomplete.

## Phase 9 · constrained kagent

**Current gap:** there is no interactive collection or validation of the
Ollama endpoint, model, or network range.

**Change:** collect endpoint, model, server CIDR, and an explicit transport
confirmation; test the endpoint; deploy the constrained agent; verify its
allowlist and RBAC; run the controlled diagnostic exercise; and complete only
after Phase 9 acceptance evidence exists.

## Phase 10 · Mac and WSL reproducibility

**Implemented:** combined host evidence must reference both platforms and pass
the runtime/command checks. Completion additionally requires current Router
readiness and external reachability, Pod recovery, and reboot plus address-change
evidence for each of Mac and Windows. Missing evidence opens the recovery menu
rather than rerunning setup. These actual trials are required for completion;
source tests do not supply them. Counterpart record transfer is an operator task.

**Change:** identify the current host, run its clean-start and acceptance
checks, retain the generated evidence location, then ask for the counterpart
host evidence when needed. The combined acceptance check decides completion.

## Phase 11 · portfolio demo

**Current gap:** the runner directs the operator to a separate demo command.

**Change:** present the seven demo stages in order, run one stage at a time,
show its verifier result, and write the final demo evidence only after all
stages pass. Cleanup remains a separate explicit menu action.

## Shared implementation order

1. Introduce a reusable Phase action model: verifier, automatic wait state,
   required input, safe action, and completion evidence.
2. Convert Phase 1, 2, 4, and 5 first because they provide the live LND,
   routing, Loop, and monitoring dependencies for later phases.
3. Add verified interactive flows for security, backup, and faults with their
   existing explicit confirmations preserved.
4. Add kagent, cross-host evidence, and demo orchestration last, using the
   earlier acceptance evidence as their completion contracts.
