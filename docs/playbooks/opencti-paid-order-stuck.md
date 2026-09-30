# Playbook: OpenCTI paid order is stuck

| | |
|---|---|
| Owner | Repository owner (sole operator) |
| Last reviewed | 2026-09-29 (v0; revise thresholds after real incidents) |
| Alert | None yet. Entered from a customer report or a manual check |
| Agent | `paid-scan-diagnosis`: `diagnose_paid_order`, `get_opencti_workload_status` |
| Related | [L402 payment gate](opencti-l402-funnel.md) |

A playbook supports judgment during an incident. Procedures with fixed steps,
such as deploys and certificate rotation, belong in runbooks.

Components (namespace `opencti-paid-scan-e2e`):

- `paid-scan-api`: the customer API (domains, quotes, orders, payment, results).
- `paid-scan-internal`: internal callbacks (evidence ingestion, scan completion, L402 payment lookup).
- `paid-scan-dispatcher`: turns paid orders into scanner Jobs through the dispatch outbox.
- `scanner-broker`: the only path from a scanner to a target; enforces scope, budget and deadline.
- Scanner Jobs: named `scan-<20 hex characters>` (the `dispatch_job_name`); their pods carry the label `app.kubernetes.io/name: scanner-worker`.
- `order-diagnostics`: the read-only endpoint behind `diagnose_paid_order`.
- `postgres`: the control database and the per-tenant databases.
- Payment: `l402-aperture`, `payment-aperture-services` and `lnd-merchant` for L402; `x402-facilitator` and `anvil` for x402.

These are the only components on the scan path. Name nothing else.

Timing facts: the stage thresholds in step 4 (1 minute, 5 minutes, and the
profile deadline + 5 minutes; Basic deadline 300 s) are the only durations for
this playbook. The L402 payment-gate timings belong to the
[L402 playbook](opencti-l402-funnel.md) and don't apply to stuck orders.

## 1. Impact

A customer paid and hasn't received a result. Money has been taken and the
customer is waiting, so treat it as urgent even if it looks like one order.

**First question: one order or many?** A single stuck order is usually that
order's data or Job. If a shared component is down (dispatcher, broker, API,
database), **every** new paid order will get stuck the same way. The workload
check in step 3 answers this.

| Scope | Severity |
|---|---|
| One order; services healthy | High: one customer waiting |
| A shared service not ready, or several orders in the same stage | **Critical**: every new paid order is affected |
| `inconsistent_records` or `payment_records_need_review` | **Critical** for that order: payment data integrity |

## 2. Mitigate first (stop the bleeding)

Reduce customer impact before looking for the root cause.

| Situation | Mitigation | Approval |
|---|---|---|
| A Deployment changed shortly before the incident (`recent_changes`) | Roll it back: `kubectl rollout undo deploy/<name>`, then `kubectl rollout status deploy/<name>`. Rollback does not undo ConfigMap or Secret changes. Verify with new activity afterwards | **Yes**: changes a running service |
| Any stuck paid order | Tell the customer: "Your payment is recorded and the scan is delayed. We're working on it; you won't need to pay again." (template in step 6) | No |
| A shared service is down (Critical) | Paid orders are **not lost**. Outbox rows stay `pending` and resume when the service returns. Tell affected customers the same, and hold any promotion or announcement that would bring more orders | No |
| The payment stage itself is broken for one rail | Stop offering that rail to new orders: remove it from the profile's `payment_methods` in `SERVICE_PROFILES_JSON`, which restarts the API. See the [L402 playbook](opencti-l402-funnel.md) | **Yes**: changes a running service |

**Never** mitigate by editing the database, asking the customer to pay again,
or deleting Jobs. Step 5 lists what's allowed.

## 3. Triage

Ask the agent, or call the tools directly:

```text
diagnose_paid_order {"tenant_id": "<T>", "order_id": "<O>"}
get_opencti_workload_status {}
```

Read these fields in order:

| Field | Meaning |
|---|---|
| **What changed recently?** workload `recent_changes` | Deployment rollouts in the last 6 hours (`name`, `revision`, `last_change`, `images`), newest first. A rollout shortly before the symptom started is the leading hypothesis. Also on each Deployment: `revision`, `last_change`, `images`. It does not show ConfigMap/Secret edits or image-tag reuse. For a human: `kubectl rollout history deploy/<name>` |
| `status` | `observed`: fresh facts. `unknown`: no diagnosis (step 7); its `next_check` is `restore_diagnostic_evidence` |
| `stage` | Where the order stopped (step 4) |
| `observed_facts.order_state` | Order state: `awaiting_payment`, `payment_pending`, `paid`, `expired`, `payment_failed` |
| `observed_facts.payment_rail` | `l402` or `x402` (payment rails are exactly l402 and x402); decides which payment backend to check |
| `observed_facts.observed_at` | Database snapshot time; the tool rejects anything older than 30 seconds |
| `observed_facts.dispatch_state_age_seconds` | How long dispatch has been in its current state |
| `observed_facts.scan_failure_reason`, `dispatch_reason` | Allowlisted codes; `other` means not a known code |
| `observed_facts.dispatch_job_name` | The scanner Job to look up in the workload output |
| workload `deployments[].ready_replicas` | Any shared service not ready means Critical (step 1) |

## 4. Diagnose: stage, threshold, cause, evidence

A waiting stage is **not** an incident. An unpaid order is the customer's
choice. **Stage plus time over the threshold** is the incident, and some stages
are incidents immediately. The thresholds come from the system's own timers:

- a 30 s dispatch lease;
- dispatch retry backoff up to 300 s;
- the Basic profile's `wall_time_seconds` of 300 s, which is also the Job's
  `activeDeadlineSeconds`.

| Stage | Incident when | Likely cause | Confirm with | Go to | Tool `next_check` |
|---|---|---|---|---|---|
| `payment` | Only after the quote/challenge expired and the order is still not `expired`/`payment_failed` | Payment backend not settling | `challenge_state` stuck in `issuing`/`verifying`/`pending`; `lnd-merchant`, `x402-facilitator`, Aperture readiness | [L402 playbook](opencti-l402-funnel.md) for L402 | `inspect_payment_confirmation_and_receipt_commit` |
| `payment_records_need_review` | Immediately | Paid, but the receipt commit is `pending` or the challenge isn't `settled` | `receipt_commit_state`, `challenge_state` | **Escalate** (data) | `inspect_payment_confirmation_and_receipt_commit` |
| `inconsistent_records` | Immediately | Paid with no payment event, or a result recorded on a scan that isn't completed | `payment_event_recorded`, `result_recorded`, `scan_state` | **Escalate** (data); take no action | `inspect_backend_reconciliation` |
| `scan_creation` | Over 1 min | Paid but no scan row | `paid-scan-api` / `paid-scan-internal` readiness | Fix the service (step 5), else escalate | `inspect_backend_reconciliation` |
| `dispatch` | Over 5 min | Dispatcher not running, or the outbox is `blocked`/`failed` | `dispatch_state`, `dispatch_reason`, `paid-scan-dispatcher` readiness | Fix the service (step 5) | `inspect_dispatcher_and_outbox` |
| `dispatch_registration` | Over 5 min | Registered with the broker, no Job yet | `scanner-broker`, `paid-scan-dispatcher` readiness; Warning events | Fix the service (step 5) | `inspect_dispatcher_and_outbox` |
| `worker_start` | Immediately | Outbox `dispatched` but scan still `queued`. The dispatcher sets both in one transaction, so this suggests a cancellation race or a partial update; the tool's next_check is `escalate_inconsistent_dispatch_state` | `dispatch_job_name`, Job existence | **Escalate** (data) | `escalate_inconsistent_dispatch_state` |
| `scan_running` | Past the deadline + 5 min (Basic: 300 s + 5 min) | Before the deadline: normal, or a worker pod that can't start (Kubernetes fails the Job at the deadline anyway). Past it: the dispatcher isn't reconciling the finished Job | Pod `waiting_reason` (`ImagePullBackOff`, `ErrImagePull`), `FailedScheduling` events, Job `condition`, `paid-scan-dispatcher` readiness | Scanner Job failed (planned playbook) | `inspect_job_and_completion_callback` |
| `scan_terminal_without_result` | Immediately | The scan failed or was cancelled | `scan_failure_reason` (`evidence_sink_unavailable`, `limit_reached`, `deadline_exceeded`, `authorization_unavailable`). `other` usually means `platform_job_failed:<reason>`, so read the Job's `condition_reason` | Fix the cause for **future** orders; this order needs **escalation** for customer remediation | `inspect_scan_attempt_and_job` |
| `result_persistence` | Over 1 min | Scan completed, result not recorded | `paid-scan-internal` readiness; `evidence_sink_unavailable` | Fix the service (step 5) | `inspect_result_ingestion` |
| `result_recorded` | Never | Normal. If the customer still sees nothing, it's API or UI delivery, which this playbook doesn't cover | — | — | `verify_result_retrieval` |

**Two recovery targets.** Fixing the system saves **future** orders. It may
not save **this** one: for example, a Job that passed its deadline is lost for
good. After fixing, re-diagnose this order and escalate it if it ended in
failure.

## 5. Fix and verify

The agent is read-only. People act, and only at the infrastructure level:

| Allowed | Example |
|---|---|
| Roll back a Deployment listed in `recent_changes` | `kubectl rollout undo deploy/<name>`, then `kubectl rollout status deploy/<name>`. **Approval required.** Does not undo ConfigMap or Secret changes |
| Fix a Deployment that isn't ready | Image, resources or Secret mount; then `kubectl rollout restart deploy/<name>` if needed |
| Restore a missing image | Re-import the offline image archive (`k3s ctr images import`) |
| Wait for automatic reconciliation | The dispatcher reconciles finished Jobs and cancellations; the broker recovers old reservations |

**Forbidden** (escalate instead):

- editing database rows by hand;
- asking the customer to pay again or creating a new order for them;
- deleting a scanner Job, outbox row or attempt;
- calling internal recovery functions such as `retry_prelaunch_attempt` from
  a shell. There is no reviewed operator interface for them yet.

Every action follows three steps:

1. **Pre-check:** record the stage and `observed_at`.
2. **Act:** make one change only.
3. **Verify:** re-run `diagnose_paid_order`. The stage must move forward, or
   the Deployment must become ready. If nothing changes within the stage
   threshold, undo the change and escalate.

## 6. Escalate and communicate

**Escalate** to the backend developer with:

- `tenant_id`, `order_id`, `stage`, `observed_at` and the reason codes;
- the relevant Deployment and Job lines from the workload tool;
- what you did and what happened afterwards.

**Never** include receipts, invoices, preimages, tokens or scan findings.

**Customer message template:**

> Your payment for order `<O>` is recorded. The scan is delayed by an
> internal issue we're fixing now. You don't need to pay again. We'll update
> you by `<time>`.

Keep an **incident log** while you work: timestamped observations, decisions
and actions. It becomes the postmortem draft.

## 7. When the agent can't help

**`status: unknown` means no diagnosis. It never means healthy.**

| `reason` | Check |
|---|---|
| `not_found_or_not_visible` | Wrong IDs, or the tenant isn't on the diagnostics allowlist |
| `access_denied` | Token mismatch between the `paid-scan-diagnostics-client` and `order-diagnostics-server` Secrets |
| `stale_or_future_observation` | Clock skew between nodes |
| `upstream_unavailable` | Is `order-diagnostics` ready? Is postgres ready? (the endpoint answers 503 on any database error) |
| `invalid_response`, `response_too_large`, `identity_mismatch` | The endpoint and the tool disagree on the contract, e.g. only one side was deployed |
| `not_configured`, `invalid_configuration` | Missing or invalid tool settings: origin, credentials, `OPENCTI_NAMESPACE` |
| `kubernetes_unavailable` (workload tool) | RBAC, or egress to the Kubernetes API |
| `playbook_unavailable` (from `get_playbook`) | The playbook ConfigMap `paid-scan-playbooks` is missing or unreadable. The agent must say so and answer from tool evidence only, with lower confidence. Redeploy with `ops/deploy-agent` |

**What the tools never see:**

- **Logs:** read them with `kubectl logs`.
- **Payment truth:** database state doesn't prove current LND or x402
  settlement.
- **Customer delivery:** `result_recorded` doesn't prove the customer
  retrieved the result.
- **Old events:** Warning events expire after about an hour.
- **Node disk and the image store:** check them directly.

## 8. Known gaps

- No alert: someone must notice first.
- No maintenance mode: new orders can't be paused as a whole.
- No operator interface for re-dispatch or remediation.
- The endpoint shows `platform_job_failed:<reason>` only as `other`.

## Worked example: dispatcher crash

1. **Report:** order `O` was paid 20 minutes ago and has no result.
2. **Triage:** `stage: dispatch`, `dispatch_state: pending`,
   `dispatch_state_age_seconds: 1150`. That's over 5 minutes, so it's an
   incident. The workload shows `paid-scan-dispatcher` with `ready_replicas: 0`,
   `CrashLoopBackOff` and `restart_count: 14`. A shared service is down, so
   it's **Critical**.
3. **Mitigate:** tell affected customers their payment is recorded and the
   scan is delayed.
4. **Diagnose:** `kubectl logs deploy/paid-scan-dispatcher --previous` shows
   a missing Secret key after a config change.
5. **Fix:** restore the key; the pod restarts.
6. **Verify:** the dispatcher is ready, and re-diagnosing shows `scan_running`,
   then `result_recorded`. No database edit was needed; the pending outbox
   row was picked up.

## Worked example: image garbage-collected (tabletop 1)

1. **Report:** a paid Basic scan has no result after 15 minutes.
2. **Triage:** `stage: scan_terminal_without_result`, `scan_failure_reason: other`.
   The Job shows `condition: Failed` and `condition_reason: DeadlineExceeded`.
   Its pod was stuck in `ImagePullBackOff`.
3. **Diagnose:** the cluster has no registry, so a worker image deleted by
   kubelet's image garbage collection can't be pulled again. Check
   `sudo k3s crictl images` and node disk; the agent can't see either.
4. **Fix:** free disk space and re-import the worker image. That fixes
   **future** orders.
5. **This order:** its deadline had passed, so the scan is lost. **Escalate**
   for a re-scan or refund. Never delete the Job or pay again.
6. **Follow-up:** protect the worker image from GC and add a disk-usage alert.
