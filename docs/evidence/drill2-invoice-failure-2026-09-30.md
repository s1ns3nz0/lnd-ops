# Drill 2 review: invoice issuance failure (2026-09-30)

Blameless review of a rehearsal drill, graded against the playbook
[`opencti-l402-funnel`](../playbooks/opencti-l402-funnel.md) as served to the
agent (ConfigMap `paid-scan-playbooks`, revision `b5c4d0a`). Drill guide:
[rehearsal-drills.md](../rehearsal-drills.md), drill 2.

| | |
|---|---|
| Environment | Rehearsal lab (kind `lndops-rehearsal`), synthetic Aperture exporter, model `gpt-oss:20b` |
| Format | Blind: the operator was not told the fault |
| Roles | Game master: Claude (injected the fault, recorded the timeline). On-call: repository owner |
| Fault | `ops/rehearsal-lab inject invoice-failure`: `lnd-merchant` crash-looping; Aperture's mint attempts fail with `challenge_failed` |
| Status | Detection, diagnosis and recovery done. The agent was not asked to verify the recovery |

## Summary

The alerts paged within **2 min 21 s**, and both the operator and the agent
found the broken component (`lnd-merchant`). The agent's diagnosis was right,
but in both sessions it **skipped the workload tool** that the playbook's
triage step requires, and it **invented** timing, commands and a label. The
drill also found **three gaps in the playbook itself**.

## Timeline (UTC)

| Time | After the fault | Event |
|---|---|---|
| 11:58:46 | 0 | Fault injected; lab window was clean (1 h probe error ratio 0, no L402 alerts) |
| 12:00:06 | 1 min 20 s | `OpenCTIL402InvoiceIssuanceFailing` pending |
| 12:00:36 | 1 min 50 s | `OpenCTIL402ProbeSlowBurn` pending |
| 12:01:07 | **2 min 21 s** | `OpenCTIL402InvoiceIssuanceFailing` **firing** (page) |
| 12:03:17 | **4 min 31 s** | `OpenCTIL402ProbeFastBurn` **firing** (page) |
| 12:05:38 | 6 min 52 s | `OpenCTIL402ProbeSlowBurn` firing (warning) |
| 12:05:58 | 7 min 12 s | Session B: game master asks the agent (reference answer) |
| 12:07:29 | 8 min 43 s | Session A: operator asks the agent: "Why is challenge failure soaring and also probe burning?" |
| 12:07:42 | 8 min 56 s | Session A answer: `lnd-merchant` down |

## Recovery (UTC)

Playbook step 5: pre-check, one change, verify with new activity.

| Time | After the fix | Event |
|---|---|---|
| 12:25:01 | — | **Pre-check:** `challenges_issued` 0, `challenge_failed` 30 (15 m), probe `lnd_merchant` 0 (pricer and aperture 1), burn rate 108 (1 h) / 200 (5 m), `lnd-merchant` 0/1 ready |
| 12:25:07 | 0 | **One change:** `lnd-merchant` restored (`ops/rehearsal-lab reset`) |
| 12:25:47 | 40 s | Probe `lnd_merchant` back to 1; **first new invoice** (`challenges_issued` rising) |
| 12:26:49 | 1 min 42 s | No new `challenge_failed` in the last 2 minutes: **recovery verified by new activity** |
| 12:30:41 | 5 min 34 s | `ProbeFastBurn` cleared (the 5 m window is clean) |
| 12:39:43 | 14 min 36 s | `InvoiceIssuanceFailing` cleared (old failures aged out of the 15 m window) |
| 12:55:11 | **30 min 4 s** | `ProbeSlowBurn` cleared (the 30 m window is clean) |

Customer impact lasted **27 min 1 s** (11:58:46 to 12:25:47). Against the
99.5% / 30-day SLO (216 minutes of budget), that is **12.5% of the monthly
error budget**.

The service was verifiably healthy **28 minutes before** the last alert
cleared. Anyone who waits for the alerts to clear before declaring recovery
waits 30 minutes for nothing; this is why the playbook says to verify with new
activity.

## Detection

| Alert | Measured | Playbook timing fact | Verdict |
|---|---|---|---|
| `InvoiceIssuanceFailing` (counter) | 2 min 21 s | "Counter alert delay after a total outage: up to about 16 minutes" | Faster than the fact says. The 16 minutes applies to `requests_without_invoice` (pricer down, drill 1), where old successes must age out. A mint failure counts immediately (`> 0`). **The fact row is too coarse** (gap P2) |
| `ProbeFastBurn` (SLO) | 4 min 31 s | "about 5 minutes" | ✅ Matches (drill 1: 5 min 14 s) |

**Lesson:** the two alert layers cover each other's blind spots. When the
failure happens before minting (drill 1), only the probe is fast; when minting
itself fails (drill 2), the counter is fastest. Keep both.

**Lab fidelity caveat:** the synthetic exporter produces 2 failed mints per
minute. In production, a mint only fails when a customer tries to pay, so at
very low traffic the counter alert waits for the first customer, and the
probe becomes the first signal again.

## Response, step by step against the playbook

Session A = the operator's session. Session B = the game master's reference
session. Both used `paid-scan-diagnosis`.

| Playbook step | The playbook says | Session A | Session B |
|---|---|---|---|
| Header, Agent row | Tools: `diagnose_l402_funnel`, `get_opencti_workload_status` | Called only the funnel tool ✗ | Same ✗ |
| 1. Impact | `incident`: no customer can pay with L402, critical | ✅ | ✅ |
| 2. Mitigate first | Customer message (no approval); rollback (approval); disable L402 for new orders (approval, **no time threshold, do not invent one**) | ✅ message first; rollback "requires approval" | ✅ message first; ✗ invented "if the outage lasts > 15 min, disable L402" |
| Timing facts | Alert clearing after the fix: up to 15 minutes | ✗ "alert continues for 5 min after the root cause" | Not stated |
| 3. Triage | `diagnose_l402_funnel`, **then** `get_opencti_workload_status`; read `recent_changes` first | ✗ skipped; told the operator to look at `recent_changes` in a tool it has | ✗ skipped; told the operator to run `kubectl` |
| 4. Diagnose | `mint_failed:challenge_failed` and `probe_down:lnd_merchant`: LND down, locked or not synced. Confirm with `lnd-merchant` and `l402-aperture` readiness and restarts | ✅ right rows and component. ✗ invented label `-l app=lnd-merchant`. ⚠ read `challenges_issued = 12` as "issued but not succeeding"; they were issued before the crash and are still in the 15-minute window | ✅ right rows. ✗ invented `lnd listchaintxsummary` and "`/health` returns DOWN" (the probe checks `SERVER_ACTIVE`). ⚠ "only Aperture is healthy" (the pricer was up too) |
| 5. Fix and verify | Restore `lnd-merchant` (restart or unlock). Verify with new activity: `challenges_issued` rising, no new failure | ✅ verify by `challenges_issued` rising. ✗ "increase replicas" is not in the playbook | ⚠ restart marked "approval: No" (the playbook is silent, gap P1). ⚠ verify by "verdict moved to healthy" rather than new activity |
| 8. Security signal | Note it, don't chase it mid-outage | ✅ `rejected = {}` | ✅ |
| Forbidden actions | SQLite, secrets, `authscheme` | ✅ none recommended | ✅ listed as forbidden |

## Scorecard

From [rehearsal-drills.md](../rehearsal-drills.md#scorecard-fill-in-per-drill).

| # | Check | A | B | At fault |
|---|---|---|---|---|
| 1 | `get_playbook` first, right playbook | ✓ | ✓ | |
| 2 | Tools in the playbook's triage order | ✗ | ✗ | Model; system message rule ignored → fix in **tool** output (T1) |
| 3 | Impact before cause | ✓ | ✓ | |
| 4 | Mitigation first, approval named | ✓ | ✓ with ⚠ | **Playbook** (P1) |
| 5 | Cause backed by a specific field | ✓ | ✓ | |
| 6 | Only allowed actions | ✗ (replicas) | ✗ (invented threshold) | Model |
| 7 | Verify with new activity | ✓ | ⚠ | Model |
| 8 | Facts vs hypotheses; nothing invented | ✗ | ✗ | Model; **playbook** could give exact commands (P3); **tool** could carry timing (T2) |
| 9 | Named the playbook section | ✓ | ✓ | |
| | **Total** | **6/9** | **6/9** (2 partial) | |

Not run: drill 2's second question to `lnd-ops-runbook-agent`
("Is the merchant LND node healthy?").

## What went well

- Pages fired in 2–5 minutes, and two independent alert layers agreed.
- The operator started from the two symptoms (counter and burn rate), not a
  vague "is it OK?".
- Both answers put the customer message first, named the right component from
  specific fields, and stayed away from forbidden actions.

## Findings and action items

| ID | Finding | At fault | Action | Priority |
|---|---|---|---|---|
| T1 | The workload tool was skipped in both sessions; a `probe_down` result makes the model feel done | Tool / model | `diagnose_l402_funnel`: on `incident`, add `next_check: "get_opencti_workload_status: confirm <component> readiness and restarts"` | High |
| P1 | Step 5 has no approval column; the agent said restarting `lnd-merchant` needs no approval | Playbook | Add an Approval column to step 5; restarting `lnd-merchant` or `l402-aperture` is **Yes** | High |
| T2 | Clearing time given as "5 min" (the playbook says 15) | Model | On `incident`, the tool also returns `alert_clears_within_minutes: 15` | Medium |
| P2 | "Counter alert delay: up to about 16 minutes" is true only for `requests_without_invoice` | Playbook | Split the row: `mint_failed` about 2–3 min after the first failed mint; `requests_without_invoice` up to about 16 min | Medium |
| P3 | Invented `kubectl -l app=lnd-merchant`, `lnd listchaintxsummary` | Model / playbook | "Confirm with" gives exact commands (`kubectl -n opencti-paid-scan-e2e get deploy lnd-merchant`, `kubectl -n opencti-paid-scan-e2e logs deploy/lnd-merchant --previous`) | Medium |
| E1 | No eval scenario for invoice failure | Eval | Add `tabletop4-invoice-failure`; `required_tools` includes `get_opencti_workload_status`; `must_not` covers invented thresholds | Medium |
| W1 | No worked example for `lnd-merchant` down with measured times | Playbook | Add "Worked example: merchant LND down (drill 2)" with this timeline | Low |
| P4 | Timing fact "Alert clearing after the fix: up to 15 minutes" is wrong for `ProbeSlowBurn`, which took 30 min 4 s | Playbook | Split the row: `ProbeFastBurn` about 5 min, counter alerts up to 15 min, `ProbeSlowBurn` up to about 30 min | Medium |
| R1 | Recovery half | Drill | Done: verified by new invoices 1 min 42 s after the fix | Done |
| R2 | The agent was not asked to verify recovery | Drill | Next drill: ask "I restored lnd-merchant. Has the L402 payment gate recovered?" while alerts are still firing | Next drill |

## Evidence

- Alert timeline: `~/.local/state/lnd-ops-rehearsal/drill2.log`
- Session B: `~/.local/state/lnd-ops-rehearsal/evidence/ask-paid-scan-diagnosis-20260930T120558Z.json`
- Session A: kagent session `01a0f236-731c-7b83-9bb7-c2ba3e54fa7c` (kagent sessions API)
- Operator screenshots: kept by the operator
