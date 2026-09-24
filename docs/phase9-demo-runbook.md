# Phase 9 demo automation

`ops/demo` is the single entry point for the portfolio demonstration. With no
arguments it shows all seven stages, explains both reversible mutation stages,
asks for the last stage to run, and executes every stage from 1 through that
selection. Each stage has a distinct terminal color. `RUN`, `PASS`, and `FAIL`
use consistent status colors.

## Start the interactive demo

Run from a clean repository revision on the prepared demo host:

```sh
ops/demo
```

Enter a number from `1` through `7`. Press Enter to run all seven stages. The
selection is cumulative, so entering `3` runs stages 1, 2, and 3. The opening
screen explains the scope before it asks for input.

For rehearsal and automation:

```sh
ops/demo --list
ops/demo --to 3 --dry-run
ops/demo --to 7
ops/demo --to 7 --no-color
```

`--dry-run` prints the exact cumulative command plan without running commands
or writing evidence. `--no-color` is intended for captured plain-text logs;
interactive terminals use color by default. `FORCE_COLOR=1` enables color when
stdout is redirected.

## Stage contract

| Stage | Color | Demonstration | Mode |
| ---: | --- | --- | --- |
| 1 | Cyan | Tools, Kubernetes access, and clean revision | Read only |
| 2 | Blue | Live testnet synchronization, peers, channel, and payment counts | Read only |
| 3 | Magenta | Payment, liquidity, Kubernetes metrics, and Grafana queries | Read only |
| 4 | Yellow | Regtest peer isolation, alert signal, Ollama/kagent diagnosis, exact policy restoration, and channel recovery | Reversible regtest mutation |
| 5 | Green | Allowlisted probe restart, cooldown, forbidden wallet action denial, and audit evidence | Read only verification of the completed exercise |
| 6 | Bright cyan | Testnet identity, channel, PVC, SCB, and Prometheus redeployment continuity | Read only |
| 7 | Bright magenta | Live Kubernetes security checks plus recovery, kagent, and cross-platform public evidence | Reversible security probes |

Stage 4 delegates to the already accepted `ops/exercise-phase7-agent` lifecycle.
On normal completion its `finally` path restores the exact NetworkPolicy and
requests peer reconnection before the wrapper continues. When Ctrl-C reaches
the child, the wrapper waits up to 180 seconds for that cleanup before exiting
`130`. A forced process kill, terminal loss, or host failure can bypass cleanup;
in that case follow
[`channel-inactive.md`](runbooks/channel-inactive.md) before another run.

Stage 5 does not restart the probe again. It validates the allowlisted restart,
cooldown, forbidden-action denial, and audit evidence produced by stage 4.

Stage 7 runs `ops/verify-security`. It performs server-side admission dry runs,
creates and deletes named disposable network and Falco probe Pods, and emits an
authorized Falco test marker. Its cleanup removes those probe Pods even when a
later check fails. It also requires the public Phase 5, 7, and 8 evidence files
to contain their pass marker and a validation date within the preceding seven
days.

Stages 4 and 5 require the Phase 7 agent deployment, one active regtest channel,
and network access from the cluster to the configured Mac Ollama endpoint. Run
the full live demonstration from the prepared Windows WSL 2 host unless the
same agent prerequisites have also been deployed on Mac.

## Evidence and safety

Every successful non-dry run writes a mode `0600` record under:

```text
${XDG_STATE_HOME:-$HOME/.local/state}/lnd-ops/evidence/phase9-demo-*.json
```

The record contains the Git revision, host type, selected stage, command names,
stage modes, results, and deferred limitations. It never captures command
stdout, wallet material, invoices, payment identifiers, macaroons, SCB bytes,
or Kubernetes credentials. The live fault uses regtest. No stage creates a
testnet payment, closes a channel, changes a wallet, deletes a PVC, or modifies
an SCB.

The command requires an empty `git status --porcelain` result before running
live steps. This checks the worktree and index; the evidence records the exact
HEAD revision. Exit `0` means every selected stage passed. Exit `1` means a failed invariant or required
operator action. A child exit `10` is reported as an operator action and becomes
wrapper exit `1`. Exit `2` means invalid CLI input, and exit `130` means the
operator interrupted the run after the wrapper waited for child cleanup. Failed
and interrupted runs do not write a passing demo evidence record.

`NO_COLOR` takes precedence over `FORCE_COLOR=1`. `--list` prints the catalog
and exits even when other execution flags are present. With no terminal input,
use `--to N`; otherwise the prompt exits with an input error.
