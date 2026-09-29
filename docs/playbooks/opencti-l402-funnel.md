# Playbook: OpenCTI L402 payment gate (Aperture)

| | |
|---|---|
| Owner | Repository owner (sole operator) |
| Last reviewed | 2026-09-29 (v0) |
| Alert | None yet. Candidate: `diagnose_l402_funnel` verdict `incident` |
| Agent | `paid-scan-diagnosis`: `diagnose_l402_funnel`, `get_opencti_workload_status` |
| Scope | **L402 only.** MPP (`authscheme` `mpp`/`l402+mpp`) and x402 are not measured. An OpenCTI test fails if MPP is enabled before MPP metrics exist |
| Related | [Stuck paid order](opencti-paid-order-stuck.md) |

Aperture is the L402 reverse proxy in front of the paid OpenCTI API. It asks
the pricer (`payment-aperture-services`) for a price, issues Lightning invoices
through `lnd-merchant`, and admits requests that prove payment.

## 1. Impact

| Verdict | Customer impact | Severity |
|---|---|---|
| `incident` | **No customer can pay with L402.** They see errors or never get an invoice | **Critical** |
| `inconclusive` | Possibly one customer mid-payment; unknown | Watch; re-check in a minute |
| `no_l402_traffic` | None, *unless* customers report errors. Then requests aren't reaching Aperture | Critical if reports exist |
| `healthy` | None | — |

Customers who already paid are affected too when `secret_lookup_error`
appears: Aperture can't check their tokens, so it rejects **paying** customers.

## 2. Mitigate first (stop the bleeding)

| Situation | Mitigation | Approval |
|---|---|---|
| Any `incident` | Tell customers: "L402 (Lightning) payment is temporarily unavailable; please use the other payment method or try later. You won't be charged twice." (template in step 6) | No |
| `incident` lasting longer than you can fix quickly | Stop offering L402 to **new** orders: remove `l402` from each profile's `payment_methods` in `SERVICE_PROFILES_JSON` (x402 stays), which restarts the API. **Before doing it, escalate to confirm that L402 orders already in flight can still finish** | **Yes**: changes a running service |

Never mitigate by editing Aperture's SQLite database, deleting or rotating
Aperture secrets or macaroon root keys (every issued token dies), or changing
`authscheme`.

## 3. Triage

Call `diagnose_l402_funnel {}` (or ask the agent), then
`get_opencti_workload_status {}`.

```text
request without token          no_credentials                  requests_without_token (normal: starts every payment)
   ─► 0. price lookup          not measured; failure stops here → no invoice
   ─► 1. invoice issued        mint_total{result="ok"}         challenges_issued
          └ failed             mint_total{result!="ok"}        mint_failed         ← INCIDENT
customer pays, retries with the L402 token
   ─► 2. token checked         verify_total{reason=…}
          ├ not paid yet       invoice_unsettled               (normal)
          ├ bad token          bad_preimage, bad_signature,    rejected            (security signal)
          │                    malformed_*, secret_not_found, caveat_unsatisfied
          └ store failed       secret_lookup_error                                 ← INCIDENT
   ─► 3. admitted              verify_total{reason="accepted"} accepted
```

`macaroon_valid` is a checkpoint *inside* step 3. Adding it to `accepted`
double-counts, so the tool never reads it.

| Field | Meaning |
|---|---|
| `status` | `unknown` means no verdict at all (step 7) |
| `verdict` | `incident`, `inconclusive`, `no_l402_traffic` or `healthy`, over the last 15 minutes |
| `incident_signals` | Why it's an incident |
| counts | `requests_without_token`, `challenges_issued`, `accepted`, `invoice_unsettled`, `rejected{reason}` |
| `security_signal` | `true` when any token was rejected. It never changes the verdict (step 8) |

**Counts, not ratios:** E2E traffic is a handful of payments, and one unpaid
invoice would swing a conversion ratio wildly. Any mint failure or store error
is a hard fault regardless of volume.

## 4. Diagnose: signal, cause, evidence

| Signal | Likely cause | Confirm with |
|---|---|---|
| `requests_without_invoice` | Requests arrive (≥ 2 without a token) but no invoice and no mint failure: a step **before** minting fails, almost always the pricer | `payment-aperture-services` readiness and restarts; `kubectl logs deploy/payment-aperture-services --previous` |
| `mint_failed:challenge_failed` | Aperture can't create invoices on `lnd-merchant`: LND down, wallet locked, not synced, or a TLS/macaroon mismatch | `lnd-merchant` and `l402-aperture` readiness and restarts; `kubectl logs deploy/l402-aperture` |
| `mint_failed:secret_failed` | Aperture's SQLite secret store can't save the new token's root key | `l402-aperture` logs; PVC `l402-aperture-db` bound; disk space |
| `mint_failed:identifier_failed` / `macaroon_failed` | In-memory steps (random ID, macaroon construction). Should essentially never happen; points at the process or host | `l402-aperture` logs and restarts; node health |
| `mint_failed:caveat_failed` | The service's caveat settings in `aperture.yaml` can't be applied | Recent change to the `l402-aperture-config` ConfigMap |
| `secret_lookup_error` | Store failing on reads: paid tokens can't be checked | Same as `secret_failed` |
| `no_l402_traffic` **with** customer reports | Requests never reach Aperture | DNS, the `l402-aperture` Service, the ingress path |

**Reality wins over a tool's verdict.** When customer reports contradict the
verdict, investigate the contradiction instead of trusting the tool.

## 5. Fix and verify

| Signal | Allowed fix |
|---|---|
| `requests_without_invoice` | Fix and restart `payment-aperture-services`. Leave Aperture alone; it only reports the pricer's failure |
| `challenge_failed` | Restore `lnd-merchant`: restart a crashed pod, or unlock the wallet by the documented procedure. Never put wallet passwords, seeds or macaroons in prompts |
| `secret_failed`, `secret_lookup_error` | Fix storage (PVC, disk) and restart `l402-aperture`. **Escalate** before touching the database file |
| `identifier_failed`, `macaroon_failed` | Restart `l402-aperture` once. If it recurs, escalate |
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

## 8. Security signal (`rejected`)

Rejected tokens are counted, not judged.

- `no_credentials` (a request with no token) is the normal start of every
  payment and never a rejection.
- `malformed_header` means a header was present but unparseable. A few are
  client bugs or noise.

Look closer when:

- `bad_signature` or `secret_not_found` climb: tokens Aperture never issued
  (forgery or probing);
- `bad_preimage` climbs: tokens presented with wrong payment proofs;
- `caveat_unsatisfied`: expired tokens, or tokens reused for another service.

The funnel can't tell *who*; that needs Aperture's security events, which
aren't collected yet. Record the counts and time window, and block nothing on
this signal alone. **During an outage, note it and come back after recovery.**

## 9. What the tools can't see

- **MPP and x402.**
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

- No alert wired to the `incident` verdict.
- No security-event collection.
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
4. **Side signal:** `rejected: {"bad_signature": 3}`. Note it and move on;
   don't chase it mid-outage.
5. **Fix:** check `kubectl logs deploy/payment-aperture-services --previous`,
   fix the cause and let it restart.
6. **Verify:** `challenges_issued` rises, customers get a 402 with an invoice,
   and the verdict becomes `healthy`.
