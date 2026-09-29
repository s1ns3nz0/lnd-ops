# OpenCTI paid order is stuck

Entry runbook for any paid-scan order that has not produced a result. It finds
**where** the order stopped and routes to the runbook that explains **why**.
Status: v0 (2026-09-29). Revise the thresholds after real incidents.

## 1. Symptom

- A customer reports a paid scan with no result, or
- an operator sees an order that has been in one stage longer than the table
  in section 3 allows.

A waiting stage is **not** an incident by itself. An unpaid order is the
customer's choice, not a fault. Stage **plus** time over the threshold is the
incident. Some stages are incidents immediately.

You need the order's `tenant_id` and `order_id`. Both are UUIDs.

## 2. Triage: ask for evidence first

Ask the `paid-scan-diagnosis` agent, or call the tool directly:

```text
diagnose_paid_order {"tenant_id": "<T>", "order_id": "<O>"}
```

Read these fields, in order:

| Field | Meaning |
|---|---|
| `status` | `observed`: the facts are fresh. `unknown`: no diagnosis; go to [diagnosis unavailable](#diagnosis-unavailable) |
| `stage` | Where the order stopped (section 3) |
| `observed_facts.observed_at` | Database snapshot time. The tool rejects anything older than 30 seconds |
| `observed_facts.dispatch_state_age_seconds` | How long dispatch has been in its current state |
| `observed_facts.scan_failure_reason`, `dispatch_reason` | Allowlisted reason codes; `other` means not a known code |
| `observed_facts.dispatch_job_name` | The scanner Job to check next |

Then, for any stage at or after dispatch, check the Kubernetes side:

```text
get_opencti_workload_status {}
```

It lists Deployment readiness, scanner Jobs, unhealthy containers and Warning
events. Match `dispatch_job_name` to a Job.

## 3. Stage → threshold → likely cause → next step

| Stage | Incident when | Likely cause | Confirm with | Next |
|---|---|---|---|---|
| `payment` | Only after the quote/challenge has expired and the order still isn't `expired` or `payment_failed` | Payment backend not settling | `challenge_state` stuck in `issuing`, `verifying` or `pending`. `lnd-merchant`, `x402-facilitator` or Aperture not ready | Payment backend unavailable (planned runbook) |
| `payment_records_need_review` | Immediately | Paid order whose receipt commit is `pending`, or whose challenge isn't `settled` | `receipt_commit_state`, `challenge_state` | **Escalate** (data). Also check the payment backends |
| `inconsistent_records` | Immediately | Paid without a payment event, or a result recorded on a scan that isn't completed | `payment_event_recorded`, `result_recorded`, `scan_state` | **Escalate** (data). Take no action |
| `scan_creation` | Over 1 min | Paid but no scan row; the backend didn't finish its post-payment steps | `paid-scan-api` / `paid-scan-internal` readiness | OpenCTI service not ready (planned) or **escalate** |
| `dispatch` | Over 5 min | Dispatcher not running, or the outbox is `blocked` or `failed` | `dispatch_state`, `dispatch_reason`, `paid-scan-dispatcher` readiness | Dispatch blocked or failed (planned) / OpenCTI service not ready (planned) |
| `dispatch_registration` | Over 5 min | Registered with the broker, but no Job created yet | `scanner-broker`, `paid-scan-dispatcher` readiness; Warning events | Same as above |
| `worker_start` | Over 5 min | Job exists but the worker pod isn't starting | Job `active`; pod `waiting_reason` (`ImagePullBackOff`, `ContainerCreating`), `FailedScheduling` events | Scanner Job failed (planned) |
| `scan_running` | Past the profile deadline + 5 min (Basic: 300 s + 5 min) | Worker hung, or the completion callback never arrived | Job `condition`/`condition_reason` (`DeadlineExceeded`); broker readiness | Scanner Job failed (planned) |
| `scan_terminal_without_result` | Immediately | The scan failed or was cancelled | `scan_failure_reason` (e.g. `evidence_sink_unavailable`, `limit_reached`, `deadline_exceeded`, `authorization_unavailable`) | Dispatch blocked or failed (planned) / Scanner Job failed (planned). Customer remediation: **escalate** |
| `result_persistence` | Over 1 min | Scan completed but its result wasn't recorded | `paid-scan-internal` readiness; `evidence_sink_unavailable` | OpenCTI service not ready (planned) |
| `result_recorded` | Never | Normal. If the customer still sees nothing, the problem is API or UI delivery, which this runbook doesn't cover | — | — |

The thresholds come from the system's own timers:

- a 30 s dispatch lease;
- dispatch retry backoff up to 300 s;
- the Basic profile `wall_time_seconds` of 300 s.

## 4. Allowed actions

The agent is read-only. People act, and **only at the infrastructure level**:

| Allowed | Example |
|---|---|
| Fix a not-ready Deployment | Image, resources or Secret mount; then `kubectl rollout restart deploy/<name>` if the fix needs it |
| Wait for automatic reconciliation | The dispatcher reconciles terminal Jobs and cancellations; the broker recovers old reservations |

**Forbidden** (always escalate instead):

- editing any database row by hand (`UPDATE`, `DELETE`);
- asking the customer to pay again, or creating a new order for them;
- deleting a scanner Job, outbox row or attempt by hand;
- calling internal recovery functions such as `retry_prelaunch_attempt` from a
  shell. There is no reviewed operator interface for them yet.

Every action follows three steps:

1. **Pre-check:** write down the current stage and `observed_at`.
2. **Act:** make one change only.
3. **Verify:** call `diagnose_paid_order` again. The stage must move forward,
   or the Deployment must become ready. If nothing changes within the stage
   threshold, undo the change and escalate.

## 5. Escalation

Escalate to the backend developer with:

- `tenant_id`, `order_id`, `stage`, `observed_at` and the reason codes;
- the relevant Deployment and Job lines from `get_opencti_workload_status`;
- what you did and what happened afterwards.

**Never** include payment receipts, invoices, preimages, tokens or customer
scan findings.

## 6. What the agent cannot see

- **Logs.** The tools return object state only. Read logs yourself with
  `kubectl logs` when a pod is crashing.
- **Payment truth.** The database's payment state doesn't prove the current LND
  or x402 settlement.
- **Customer delivery.** `result_recorded` doesn't prove the customer retrieved
  the result.
- **Old events.** Warning events expire after about an hour, so a missing
  event is not proof that nothing happened.

## Diagnosis unavailable

`status: unknown` means **no diagnosis**. It is never "healthy". The `reason`
field says why:

| `reason` | Check |
|---|---|
| `not_found_or_not_visible` | Wrong IDs, or the tenant isn't on the diagnostics allowlist |
| `access_denied` | Token mismatch between the `paid-scan-diagnostics-client` and `order-diagnostics-server` Secrets |
| `stale_or_future_observation` | Clock skew between the nodes |
| `upstream_unavailable` | Is `order-diagnostics` ready? Is postgres ready? The endpoint answers 503 on any database error |
| `invalid_response`, `response_too_large`, `identity_mismatch` | The endpoint and the tool disagree on the contract, for example after deploying only one side. Compare the deployed versions |
| `not_configured`, `invalid_configuration` | Missing or invalid tool settings: origin, credential files or `OPENCTI_NAMESPACE` |
| `kubernetes_unavailable` (workload tool) | RBAC or the NetworkPolicy egress to the Kubernetes API |

## Worked example (for study)

1. **Report:** tenant `T`, order `O` was paid 20 minutes ago and has no result.
2. **Triage:** `stage: dispatch`, `dispatch_state: pending`, `dispatch_state_age_seconds: 1150`.
   That's over the 5-minute threshold, so this is an **incident**.
3. **Workload:** `paid-scan-dispatcher` shows `ready_replicas: 0`. Its container
   has `waiting_reason: CrashLoopBackOff` and `restart_count: 14`.
4. **Hypothesis:** the dispatcher crashes, so nothing leases the outbox.
5. **Logs:** `kubectl -n opencti-paid-scan-e2e logs deploy/paid-scan-dispatcher --previous`
   shows the crash cause, for example a missing Secret key after a config change.
6. **Act:** restore the Secret key; the pod restarts by itself or with
   `rollout restart`.
7. **Verify:** the dispatcher is ready. Re-diagnosing shows `worker_start`,
   then `scan_running`, then `result_recorded`. No database edit was needed:
   the outbox row was still `pending` and the dispatcher picked it up.
