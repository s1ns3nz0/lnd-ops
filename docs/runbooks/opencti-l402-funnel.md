# OpenCTI L402 payment gate (Aperture)

How to read `diagnose_l402_funnel` and respond. Aperture is the L402 reverse
proxy in front of the paid OpenCTI API: it issues Lightning invoices and admits
requests that prove payment. Status: v0 (2026-09-29).

**Scope: L402 only.** MPP (Aperture `authscheme` `mpp` or `l402+mpp`) and the
x402 rail are not measured. `no_l402_traffic` never means "no payments". An
OpenCTI test fails if anyone enables MPP before MPP metrics exist.

## 1. The funnel

```text
request without token             aperture_l402_verify_total{reason="no_credentials"}  (normal: triggers the invoice, not counted)
        ─► 1. invoice issued      aperture_l402_mint_total{result="ok"}          challenges_issued
               └ failed           {result!="ok"}                                  mint_failed      ← INCIDENT
customer pays, retries with L402 token
           ─► 2. token checked    aperture_l402_verify_total{reason=...}
               ├ not paid yet     invoice_unsettled                               invoice_unsettled (normal)
               ├ bad token        bad_preimage, bad_signature, malformed_*,       rejected         (security signal)
               │                  secret_not_found, caveat_unsatisfied
               └ store failed     secret_lookup_error                             secret_lookup_error ← INCIDENT
           ─► 3. admitted         {reason="accepted"}                             accepted
```

`macaroon_valid` is a checkpoint *inside* step 3 and is never counted
separately. Adding it to `accepted` double-counts.

## 2. Triage

Ask the `paid-scan-diagnosis` agent about the payment gate, or call
`diagnose_l402_funnel {}`. Read these fields in order:

| Field | Meaning |
|---|---|
| `status` | `unknown` means no verdict at all. See section 5 |
| `verdict` | `incident`, `no_l402_traffic` or `healthy`, over the last 15 minutes |
| `incident_signals` | Why it's an incident, e.g. `mint_failed:challenge_failed`, `secret_lookup_error` |
| counts | `challenges_issued`, `accepted`, `invoice_unsettled`, `rejected{reason}` |
| `security_signal` | `true` when any token was rejected. It never changes the verdict |

## 3. Verdicts

| Verdict | Means | Do |
|---|---|---|
| `healthy` | Invoices are issued and nothing is failing | Nothing. Low `accepted` against `challenges_issued` is a business question, not a fault |
| `no_l402_traffic` | Nothing happened on L402 in 15 minutes | Nothing, unless customers report failures. Then check two things the funnel can't see: the pricer (`payment-aperture-services` readiness), and whether requests reach Aperture at all (DNS, Service, ingress) |
| `incident` | Invoices can't be issued, or Aperture's store failed. **No customer can pay** | Section 4 |

**Why counts and not ratios:** E2E traffic is a handful of payments. One
unpaid invoice would swing a conversion ratio wildly. Any mint failure or
store error is a hard fault regardless of volume.

## 4. Incident response

| Signal | Likely cause | Confirm with | Allowed action |
|---|---|---|---|
| `mint_failed:challenge_failed` | Aperture can't create invoices on `lnd-merchant`: LND down, wallet locked, not synced, or a TLS/macaroon mismatch | `get_opencti_workload_status`: `lnd-merchant` and `l402-aperture` readiness and restarts. Then `kubectl logs deploy/l402-aperture` | Restore `lnd-merchant`, e.g. restart a crashed pod or unlock the wallet by the documented procedure. Never put wallet passwords, seeds or macaroons in prompts |
| `mint_failed:secret_failed` | Aperture's secret store (SQLite) can't save the new token's root key | `l402-aperture` logs; PVC `l402-aperture-db` bound; disk space | Fix storage and restart `l402-aperture`. **Escalate** before touching the database file |
| `mint_failed:identifier_failed` / `macaroon_failed` | In-memory steps (random ID, macaroon construction). Should essentially never happen; points at the process or host | `l402-aperture` logs and restarts; node health | Restart `l402-aperture` once. If it recurs, escalate |
| `mint_failed:caveat_failed` | The service's caveat settings in `aperture.yaml` (e.g. constraints, timeouts) can't be applied | Recent change to the `l402-aperture-config` ConfigMap | Roll back the last config change. Escalate otherwise |
| `secret_lookup_error` | Store failing on reads: tokens customers already paid for can't be checked | Same as `secret_failed` | Same. This rejects **paying** customers, so escalate immediately |

Always follow the three steps from the [stuck order runbook](opencti-paid-order-stuck.md):

1. **Pre-check:** record the verdict and counts.
2. **Act:** make one change.
3. **Verify:** re-run `diagnose_l402_funnel`.

Because the window is 15 minutes, **a fixed fault stays visible for up to 15
minutes**. Verify with **new** successful activity: `challenges_issued`
rising with no new `mint_failed`. Waiting for the old count to disappear
doesn't prove anything.

**Forbidden:** editing Aperture's SQLite database, deleting or rotating
Aperture secrets or macaroon root keys (all issued tokens die), or changing
`authscheme`.

## 5. When `status` is `unknown`

| `reason` | Check |
|---|---|
| `aperture_not_scraped` | Is Aperture running? Does the `l402-aperture` Service expose port `metrics` (9000)? Is `prometheus.enabled: true` in its config? In Prometheus, check the `aperture` target |
| `prometheus_unavailable` | Is Prometheus in `lndops-monitoring` up? Does the paid-scan NetworkPolicy allow egress to it on 9090? |

No data is never "healthy".

## 6. Security signal (`rejected`)

Rejected tokens are counted, not judged. A request with **no** token is
`no_credentials`, the normal start of every payment, and is never a rejection.
`malformed_header` means a header was present but unparseable. A few of those
are client bugs or noise. Look closer when:

- `bad_signature` or `secret_not_found` climb: someone is presenting tokens
  Aperture never issued (forgery or probing);
- `bad_preimage` climbs: tokens presented with wrong payment proofs;
- `caveat_unsatisfied`: expired tokens, or tokens reused for another service.

The funnel can't tell *who*. Correlating sources needs Aperture's security
events, which aren't collected yet. Record the counts and time window. Don't
block anything on this signal alone.

## 7. What this tool can't see

- **MPP and x402**, as explained above.
- **Pricing failures.** Aperture asks `payment-aperture-services` for the price
  *before* minting (`proxy/proxy.go`). If the pricer is down, customers get
  errors, but no mint is attempted and the funnel shows `no_l402_traffic`. When
  customers report errors during `no_l402_traffic`, check
  `payment-aperture-services` readiness with `get_opencti_workload_status`.
- **Individual requests.** Counts only: no client, token or amount.
- **Restarts.** Counters reset when Aperture restarts. Every label starts at 0,
  so first events after a restart are still counted, but a restart inside the
  window can blur the counts.
- **Payment truth.** `accepted` means Aperture saw a settled invoice at that
  moment. It is not an accounting record.
- **The order.** Whether a specific paid order then scanned is
  `diagnose_paid_order`'s job.

## Worked example (for study)

1. **Report:** at 14:05 two customers say "payment page errors".
2. **Funnel:** `verdict: incident`, `incident_signals: ["mint_failed:challenge_failed"]`,
   `mint_failed: {"challenge_failed": 7}`, `challenges_issued: 0`.
3. **Meaning:** Aperture can't create invoices, so **nobody** can start
   paying. This is not a single customer's problem.
4. **Workload:** `lnd-merchant` has `ready_replicas: 0` and container
   `restart_count: 5`, with `last_terminated_reason: OOMKilled`.
5. **Hypothesis:** the merchant LND ran out of memory, so invoice creation fails.
6. **Act:** raise the `lnd-merchant` memory limit by the reviewed chart change
   and let it restart. **Don't** touch Aperture; it was only the messenger.
7. **Verify:** `lnd-merchant` ready; a test request gets a 402 with an
   invoice; the funnel shows `challenges_issued` rising and no new
   `challenge_failed`. The old 7 age out of the 15-minute window.
8. **Follow-up:** check for orders stuck in `payment` with the
   [stuck order runbook](opencti-paid-order-stuck.md).
