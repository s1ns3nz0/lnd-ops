# Interactive Phase Runner Roadmap

`lndops` should keep one Phase on screen until its completion verifier passes.
Each Phase follows the same contract: show a compact live status, collect only
the input needed for the next action, perform that action, and immediately
recheck. The command prompt returns only after the selected Phase is complete
or the operator explicitly interrupts it.

## Phase 1 · regtest foundation

**Current gap:** the runner only describes wallet creation, seed custody,
channels, and payments.

**Change:** detect whether the selected regtest workspace already has both
wallets. For an existing workspace, unlock both wallets interactively. For a
new workspace, ask once before creating each wallet, show the seed custody
checkpoint, then create the local channel and run the bidirectional payment
exercise. Recheck the regtest verifier after every action.

## Phase 2 · persistent testnet node

**Current gap:** wallet unlock is interactive, but peer, channel, and payment
readiness is not presented as a sequence.

**Change:** retain the existing unlock flow, then display the next missing
testnet condition only: chain/graph sync, peer connection, public channel, or
fresh outgoing/incoming payment. Poll automatic conditions and recheck after
each operator-confirmed condition.

## Phase 3 · testnet Router Node

**Current gap:** completed in this change.

**Change:** keep the Router progress screen active through chain/graph sync,
public URI, two public channels, policy application, and external forwarding.
Automatic conditions are polled with compact progress lines. Policy
application is the only prompt after the node is exposed. The Phase succeeds
only when the forwarding verifier passes.

## Phase 4 · Loop liquidity management

**Current gap:** Loop is only described even though a read-only quote verifier
already exists.

**Change:** prompt for the local path of the dedicated Loop macaroon, validate
that it is readable without echoing it, deploy Loop, wait for its workload,
then run the health and read-only quote verifier. Never offer a swap in this
runner.

## Phase 5 · observability

**Current gap:** the runner verifies only monitoring infrastructure, so it can
finish before it sees live LND metrics and payment history.

**Change:** deploy the shared monitoring stack when absent, unlock the selected
wallet when required, wait for collector targets to become healthy, and verify
the selected profile rather than infrastructure alone. When fresh payment data
is missing, keep the Phase screen open and recheck after the next payment.

## Phase 6 · security baseline

**Current gap:** deployment is automatic but completion remains a generic
manual instruction.

**Change:** deploy Kyverno and Falco, wait for their workloads, run the
read-only security verifier, then create Phase 6 acceptance evidence only
after it passes. Report the failing policy or runtime signal in plain language.

## Phase 7 · backup and recovery

**Current gap:** the runner does not expose the existing recovery evidence
gates.

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

**Current gap:** host evidence is created outside the runner with no status
handoff.

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
