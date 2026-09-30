# Playbook: OpenCTI L402 payment gate (Aperture)

| | |
|---|---|
| Owner | Repository owner (sole operator) |
| Last reviewed | 2026-09-29 (v0) |
| Alerts | `OpenCTIL402InvoiceIssuanceFailing`, `OpenCTIL402SecretStoreFailing`, `OpenCTIL402RequestsWithoutInvoice` (critical); `OpenCTIL402ProbeFastBurn` (critical); `OpenCTIL402ProbeSlowBurn` (warning); `OpenCTIL402ProbeAbsent` (warning); `OpenCTIL402MetricsAbsent` (warning), in `charts/monitoring-rules.yaml`. Same thresholds as the tool. Delivery: Alertmanager UI only (no external receiver yet). They use 15-minute windows, so an alert **stays firing up to 15 minutes after the fix**: verify with new activity, not with the alert clearing |
| Agent | `paid-scan-diagnosis`: `diagnose_l402_funnel`, `get_opencti_workload_status` |
| Scope | **L402 only.** MPP (`authscheme` `mpp`/`l402+mpp`) and x402 are not measured. An OpenCTI test fails if MPP is enabled before MPP metrics exist |
| Related | [Stuck paid order](opencti-paid-order-stuck.md); [SLO and burn-rate design](../slo-l402.md) |

Aperture is the L402 reverse proxy in front of the paid OpenCTI API. It asks
the pricer (`payment-aperture-services`) for a price, issues Lightning invoices
through `lnd-merchant`, and admits requests that prove payment.

Components:

- `l402-aperture`: Aperture, the L402 proxy.
- `payment-aperture-services`: the pricer AND the receipt service; there is no separate pricer service.
- `lnd-merchant`: the LND node that creates invoices.
- `paid-scan-api`: the API behind Aperture.
- `x402-facilitator`: the other payment rail's verifier.

These are the only components on the L402 path.

## 1. Impact

| Verdict | Customer impact | Severity |
|---|---|---|
| `incident` | **No customer can pay with L402.** They see errors or never get an invoice | **Critical** |
| `inconclusive` | Possibly one customer mid-payment; unknown | Watch; re-check in a minute |
| `no_l402_traffic` | None, *unless* customers report errors. Then requests aren't reaching Aperture | Critical if reports exist |
| `healthy` | None | — |

Customers who already paid are affected too when `secret_store_error`
appears: Aperture can't check their tokens, so it rejects **paying** customers.

## 2. Mitigate first (stop the bleeding)

| Situation | Mitigation | Approval |
|---|---|---|
| Any `incident` | Tell customers: "L402 (Lightning) payment is temporarily unavailable; please use the other payment method or try later. You won't be charged twice." (template in step 6) | No |
| A Deployment changed shortly before the incident (`recent_changes`) | Roll it back: `kubectl rollout undo deploy/<name>`, then `kubectl rollout status deploy/<name>`. Rollback does not undo ConfigMap or Secret changes. Verify with new activity afterwards | **Yes**: changes a running service |
| `incident` lasting longer than you can fix quickly | Stop offering L402 to **new** orders: remove `l402` from each profile's `payment_methods` in `SERVICE_PROFILES_JSON` (x402 stays), which restarts the API. **Before doing it, escalate to confirm that L402 orders already in flight can still finish** | **Yes**: changes a running service |

The only alternative payment rail is x402. There is no card, PayPal or other method.
The playbook sets no time threshold for disabling L402; how long to wait is the approver's decision. Do not invent one.

**Timing facts.** These are the only durations that apply; they were measured in
the rehearsal lab on 2026-09-30. Use them instead of inventing others.

| Fact | Value | Why |
|---|---|---|
| Probe fast-burn alert after a total outage | about 5 minutes | Probe every 60 s, 1 h + 5 m burn windows ([SLO design](../slo-l402.md)) |
| Counter alert delay after a total outage | up to about 16 minutes | The 15-minute counter window still holds earlier successes; then `for: 1m` |
| Alert clearing after the fix | up to 15 minutes | The window keeps counting the failure until it ages out |
| When to re-check after a fix | after at least one new request | Verification needs new activity (`challenges_issued` rising), not elapsed time |
| Any other time limit | none | Waiting times not listed here are the approver's decision |

Never mitigate by editing Aperture's SQLite database, deleting or rotating
Aperture secrets or macaroon root keys (every issued token dies), or changing
`authscheme`.

## 3. Triage

Call `diagnose_l402_funnel {}` (or ask the agent), then
`get_opencti_workload_status {}`.

```text
request without token          missing_credentials             requests_without_token (normal: starts every payment)
   ─► 0. price lookup          not measured; failure stops here → no invoice
   ─► 1. invoice issued        mint_total{result="ok"}         challenges_issued
          └ failed             mint_total{result!="ok"}        mint_failed         ← INCIDENT
customer pays, retries with the L402 token
   ─► 2. token checked         verify_total{reason=…}
          ├ not paid yet       invoice_state_mismatch          (normal)
          ├ bad token          payment_proof_mismatch, invalid_signature,   rejected   (security signal)
          │                    malformed_credentials, malformed_identifier,
          │                    unknown_credential, restriction_failure
          └ store failed       secret_store_error              ← INCIDENT
   ─► 3. admitted              verify_total{reason="accepted"} accepted
```

`credential_verified` is a checkpoint *inside* step 3. Adding it to `accepted`
double-counts, so the tool never reads it. Label values match Aperture's
security-event reasons.

| Field | Meaning |
|---|---|
| **What changed recently?** workload `recent_changes` | Read this first. Deployment rollouts in the last 6 hours (`name`, `revision`, `last_change`, `images`), newest first. A rollout shortly before the symptom started is the leading hypothesis. It does not show ConfigMap/Secret edits or image-tag reuse. For a human: `kubectl rollout history deploy/<name>` |
| `status` | `unknown` means no verdict at all (step 7) |
| `verdict` | `incident`, `inconclusive`, `no_l402_traffic` or `healthy`, over the last 15 minutes |
| `incident_signals` | Why it's an incident |
| counts | `requests_without_token`, `challenges_issued`, `accepted`, `invoice_state_mismatch`, `rejected{reason}` |
| `rejected_total`, `rejected_baseline_per_15m` | Rejections in the window, and the per-15-minute average of the previous 24 hours (excluding the window) |
| `probe_status` | `observed` or `missing`: whether the component health probe (job `l402-probe`) is scraped. Missing never changes the counter verdict |
| `probe_components` | Last probe result per component: `pricer`, `lnd_merchant`, `aperture`, each `up`, `down` or `missing` |
| `probe_success_1h` | 1 minus the 1-hour probe error ratio; `null` if missing |
| `slo_burn_rate_1h`, `slo_burn_rate_5m` | Probe error ratio divided by the 0.005 budget (SLO 99.5% over 30 days); `null` if missing. 14.4 or more on both windows is `probe_fast_burn` |
| `security_signal` | `none` (no rejections), `present` (rejections, not unusual) or `elevated` (at least 20 and 10x the baseline, or any 20+ when the baseline is 0). It never changes the verdict (step 8) |

**Counts, not ratios:** E2E traffic is a handful of payments, and one unpaid
invoice would swing a conversion ratio wildly. Any mint failure or store error
is a hard fault regardless of volume.

## 4. Diagnose: signal, cause, evidence

| Signal | Likely cause | Confirm with |
|---|---|---|
| `requests_without_invoice` | Requests arrive (≥ 2 without a token) but no invoice and no mint failure: a step **before** minting fails, almost always the pricer. `payment-aperture-services` is the pricer itself; do not look for a separate pricer service | `payment-aperture-services` readiness and restarts; `kubectl logs deploy/payment-aperture-services --previous` |
| `mint_failed:challenge_failed` | Aperture can't create invoices on `lnd-merchant`: LND down, wallet locked, not synced, or a TLS/macaroon mismatch | `lnd-merchant` and `l402-aperture` readiness and restarts; `kubectl logs deploy/l402-aperture` |
| `mint_failed:secret_failed` | Aperture's SQLite secret store can't save the new token's root key | `l402-aperture` logs; PVC `l402-aperture-db` bound; disk space |
| `mint_failed:identifier_failed` / `macaroon_failed` | In-memory steps (random ID, macaroon construction). Should essentially never happen; points at the process or host | `l402-aperture` logs and restarts; node health |
| `mint_failed:caveat_failed` | The service's caveat settings in `aperture.yaml` can't be applied | Recent change to the `l402-aperture-config` ConfigMap |
| `probe_fast_burn` | The component health probe has failed long enough to burn the SLO budget fast, even if counters still look healthy. Name the failing component from `probe_components` | Rows `probe_down:<component>` below; `probe_components`, `slo_burn_rate_1h` |
| `probe_down:pricer` | `payment-aperture-services` `/health` fails (same as `requests_without_invoice`). That health check also calls Aperture's proxy port, so **if `probe_down:aperture` is present too, suspect Aperture first** | `payment-aperture-services` readiness and restarts; `kubectl logs deploy/payment-aperture-services --previous` |
| `probe_down:lnd_merchant` | `lnd-merchant` is not `SERVER_ACTIVE`: down, locked or not synced (same as `challenge_failed`) | `lnd-merchant` and `l402-aperture` readiness and restarts; `kubectl logs deploy/l402-aperture` |
| `probe_down:aperture` | `l402-aperture` is not accepting connections | `l402-aperture` readiness, restarts and Service |
| `secret_store_error` | Store failing on reads: paid tokens can't be checked | Same as `secret_failed` |
| `no_l402_traffic` **with** customer reports | Requests never reach Aperture | DNS, the `l402-aperture` Service, the ingress path |

**Reality wins over a tool's verdict.** When customer reports contradict the
verdict, investigate the contradiction instead of trusting the tool.

## 5. Fix and verify

| Signal | Allowed fix |
|---|---|
| `requests_without_invoice` | Fix and restart `payment-aperture-services`. Leave Aperture alone; it only reports the pricer's failure |
| `challenge_failed` | Restore `lnd-merchant`: restart a crashed pod, or unlock the wallet by the documented procedure. Never put wallet passwords, seeds or macaroons in prompts |
| `secret_failed`, `secret_store_error` | Fix storage (PVC, disk) and restart `l402-aperture`. **Escalate** before touching the database file |
| `identifier_failed`, `macaroon_failed` | Restart `l402-aperture` once. If it recurs, escalate |
| Any signal, with a matching entry in `recent_changes` | Roll back that Deployment: `kubectl rollout undo deploy/<name>`, then `kubectl rollout status deploy/<name>`. **Approval required.** Does not undo ConfigMap or Secret changes |
| `caveat_failed` | Roll back the last config change; otherwise escalate |

Follow the three steps:

1. **Pre-check:** record the verdict and counts.
2. **Act:** make one change.
3. **Verify:** re-run the funnel.

**Verify with new activity.** The window is 15 minutes, so a fixed fault stays
visible for up to 15 minutes. Look for `challenges_issued` rising with no new
failure signal. The old count disappearing proves nothing.

## 6. Escalate and communicate

**Escalate** with:

- the verdict, `incident_signals` and counts, plus `observed_at`;
- the relevant workload lines;
- what you did and what happened afterwards.

**Never** include invoices, preimages, macaroons or tokens.

**Customer message template:**

> Lightning (L402) payment is temporarily unavailable due to an issue we're
> fixing now. You haven't been charged for failed attempts. Please use
> `<other method>` or try again after `<time>`.

Keep a timestamped incident log. It becomes the postmortem draft.

## 7. When `status` is `unknown`

`unknown` never means healthy.

| `reason` | Check |
|---|---|
| `aperture_not_scraped` | Is Aperture running? Does the `l402-aperture` Service expose port `metrics` (9000)? Is `prometheus.enabled: true` in its config? Check the `aperture` target in Prometheus |
| `prometheus_unavailable` | Is Prometheus in `lndops-monitoring` up? Does the paid-scan NetworkPolicy allow egress to it on 9090? |
| `playbook_unavailable` (from `get_playbook`) | The playbook ConfigMap `paid-scan-playbooks` is missing or unreadable. The agent must say so and answer from tool evidence only, with lower confidence. Redeploy with `ops/deploy-agent` |

## 8. Security signal (`rejected`)

Rejected tokens are counted, not judged.

- `missing_credentials` (a request with no token) is the normal start of every
  payment and never a rejection.
- `malformed_credentials` means a header was present but unparseable. A few are
  client bugs or noise.

Look closer when:

- `invalid_signature` or `unknown_credential` climb: tokens Aperture never issued
  (forgery or probing);
- `payment_proof_mismatch` climbs: tokens presented with wrong payment proofs;
- `restriction_failure`: expired tokens, or tokens reused for another service.

**"Healthy" is about availability, not security.** Alerts and the verdict
ignore rejections by design, so a jump in rejections is found by looking, not
by an alert. When `security_signal` is `elevated`, treat it as a low-severity
security investigation until there's evidence that a forged token succeeded.
`present` means rejections exist but are not unusual.

**Test competing hypotheses before acting.** They need different responses:

| Hypothesis | Points to it | Test |
|---|---|---|
| One client stuck in a retry loop | Steady rate; the same reason over and over | Security events: one `credential_ref` or `source_ip` repeating |
| Aperture's database or root key was reset | `unknown_credential` / `invalid_signature` start right after an Aperture restart or PVC change; legitimate customers are affected | Aperture restart time; `l402-aperture-db` PVC events. **A block here would shut out paying customers** |
| Forgery or probing | Many distinct credentials; no link to a restart | Security events: many `credential_ref` values from few sources |

The funnel can't tell *who*. That needs Aperture's security events, which
aren't collected yet. Record the counts and time window, and block nothing on
this signal alone. **During an outage, note it and come back after recovery.**

**Don't turn on debug logs casually.** Aperture logs rejections only at
`debug` level, and the error text includes the submitted preimage. For a
legitimate customer's mistake, that writes their payment proof to the logs.
Enabling it needs approval and a short time limit. Structured security events
are the intended way to get this detail.

## 9. What the tools can't see

- **MPP and x402.**
- **Invoice issuance end to end.** The probe checks component health only; all components can be up while invoices still fail. Counters cover that, more slowly.
- **The pricer itself.** It's seen only indirectly, as `requests_without_invoice`.
  A single such request is only `inconclusive`.
- **Individual requests.** Counts only: no client, token or amount.
- **Restarts inside the window.** Counters reset when Aperture restarts.
  Labels start at 0, so first events still count, but a restart inside the
  window can blur the counts.
- **Payment truth.** `accepted` is Aperture's view at that moment, not an
  accounting record.
- **The order.** That's the [stuck order playbook](opencti-paid-order-stuck.md)'s job.

## 10. Known gaps

- Alerts reach only the Alertmanager UI. No notification channel has been chosen yet.
- No security-event collection, so no per-source or per-credential correlation. The fork branch `feat/l402-security-events` provides the events; collection is the missing step.
- The rejection baseline is only a 24-hour average and resets with Prometheus retention; after a restart or on a new deployment it may be low or zero.
- No MPP metrics.
- No pricer metric.
- Disabling L402 for new orders is a config change and restart, not a switch.

## Worked example: merchant LND out of memory

1. **Report:** at 14:05 two customers see payment page errors.
2. **Triage:** `verdict: incident`, `mint_failed: {"challenge_failed": 7}`,
   `challenges_issued: 0`. **Critical**: nobody can pay with L402.
3. **Mitigate:** post the customer message.
4. **Diagnose:** `lnd-merchant` shows `ready_replicas: 0`, `restart_count: 5`
   and `last_terminated_reason: OOMKilled`. It ran out of memory, so invoice
   creation fails.
5. **Fix:** raise the `lnd-merchant` memory limit with a reviewed chart change.
   Don't touch Aperture; it was only the messenger.
6. **Verify:** `lnd-merchant` is ready and `challenges_issued` rises with no
   new `challenge_failed`. The old 7 age out of the window.
7. **Follow-up:** check for orders stuck in `payment` with the
   [stuck order playbook](opencti-paid-order-stuck.md).

## Worked example: dead pricer (tabletop 2)

1. **Report:** at 16:20 three customers see an error on the payment button.
   None was charged.
2. **Triage:** `challenges_issued: 0`, no `mint_failed`,
   `requests_without_token: 3`. That's `verdict: incident` with
   `requests_without_invoice`. Before this signal existed, the same data read
   `no_l402_traffic`. The customer reports contradicted it, and reality wins.
3. **Workload:** `l402-aperture` and `lnd-merchant` are ready.
   `payment-aperture-services` shows `ready_replicas: 0`, `CrashLoopBackOff`
   and `restart_count: 11`.
4. **Side signal:** `security_signal: present` (`rejected: {"invalid_signature": 3}`). Note it and move on;
   don't chase it mid-outage.
5. **Fix:** check `kubectl logs deploy/payment-aperture-services --previous`,
   fix the cause and let it restart.
6. **Verify:** `challenges_issued` rises, customers get a 402 with an invoice,
   and the verdict becomes `healthy`.

## Worked example: rejection spike at night (tabletop 3)

1. **Morning check (02:10):** `verdict: healthy`, no alerts, `accepted: 5`,
   `challenges_issued: 41`, but `rejected: {"invalid_signature": 212,
   "unknown_credential": 187, "malformed_identifier": 3}`, `rejected_total: 402`,
   `rejected_baseline_per_15m: 1.5` and `security_signal: elevated`.
2. **Impact:** paying customers get through, so there's no availability
   incident. `security_signal` is `elevated`, so open a low-severity security
   investigation.
3. **Hypotheses:** a retry loop, an Aperture database or root key reset, or
   forgery. Check first whether Aperture restarted or its PVC changed. If so,
   a reset is likely and legitimate customers are affected.
4. **Don't block.** There's nothing to block by, and under the reset
   hypothesis a block shuts out paying customers. Watch `secret_store_error`
   in case the lookups load the store.
5. **Escalate** to whoever handles security, with counts and time windows.
6. **Lesson:** the metrics detected the problem, but only per-request
   security events can tell the three hypotheses apart. This exercise is why
   security-event collection is the next monitoring slice.
