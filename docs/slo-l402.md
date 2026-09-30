# L402 payment gate: SLO and burn-rate alerting (design)

Status: design agreed 2026-09-30; not implemented yet.

## Why

In rehearsal scenario 1 (pricer down), the counter-based alert
`OpenCTIL402RequestsWithoutInvoice` fired about **16 minutes** after the
outage started. The alert rule isn't at fault. The cause is **low traffic
combined with window-based counters**: with about 2 payments per minute, the
successes recorded before the failure stay in the 15-minute window until they
age out. The Google SRE Workbook (ch. 5, low-traffic services) recommends
synthetic probing for this case, with burn-rate alerting on the probe SLI.

## SLIs

| SLI | Source | Used for |
|---|---|---|
| **Probe availability** | Prometheus blackbox exporter sends one tokenless request to Aperture every 60 s. Success = HTTP **402** with a `WWW-Authenticate` header containing `L402`, which proves the path Aperture → pricer → `lnd-merchant` issued an invoice | **Alerting** (fast, traffic-independent) |
| Real-traffic invoice success | `aperture_l402_mint_total{result="ok"}` / `aperture_l402_verify_total{reason="missing_credentials"}` | **SLO reporting** only (too noisy to alert on at low traffic) |

The probe uses the same path as a customer, so an `lnd-merchant` failure is
detected too. Probing only the pricer would miss it.

## SLO

**99.5% probe availability over 30 days** (error budget 0.5%).

99.9% was rejected: at 60 probes per hour, the fast-burn threshold (1.44% over
1 h) is a single failed probe, so one transient failure would page.

## Alerts (multiwindow, multi-burn-rate)

| Alert | Condition | Severity | Meaning |
|---|---|---|---|
| `OpenCTIL402ProbeFastBurn` | burn rate ≥ 14.4 over **1 h and 5 m** | critical (page) | About 2% of the monthly budget spent in an hour. Expected to catch a total outage in **about 5 minutes** |
| `OpenCTIL402ProbeSlowBurn` | burn rate ≥ 6 over **6 h and 30 m** | warning (ticket) | Persistent partial failure |

The burn rate is the error ratio over the window divided by 0.005. The four
existing counter alerts stay as **cause** alerts for diagnosis. Each alert
carries `runbook_url` to `docs/playbooks/opencti-l402-funnel.md`.

## Probe side effect: invoices

Each probe creates a real unpaid invoice on `lnd-merchant`.

- Interval **60 s**, which is 1,440 invoices per day.
- LND cancels unpaid invoices when they expire; its `InvoiceExpiryWatcher`
  handles automatic cancellation of expired invoices. With
  `gc-canceled-invoices-on-the-fly=true` on `lnd-merchant`, canceled invoices
  are deleted, so the invoice DB reaches a steady state instead of growing.
- To verify at build time: the expiry Aperture sets on its invoices (LND's
  default is about 1 day), and that probe invoices are identifiable (for
  example a dedicated probe route in Aperture's config).

## Agent

`diagnose_l402_funnel` adds `probe_success_1h`, `slo_burn_rate_1h` and
`slo_burn_rate_5m` from fixed PromQL. `unknown` applies when the probe isn't
scraped. The playbook's timing facts are updated from the next rehearsal
measurement.

## Lab

The synthetic Aperture exporter gains a probe endpoint. It returns 402 with
`WWW-Authenticate: L402 …` normally, and 500 during `pricer-down` and
`invoice-failure`. The blackbox exporter and the probe scrape job run in the
lab like in production. Success means scenario 1's detection time is
measured and compared with the 16-minute baseline.

## Out of scope

- Aperture HTTP status and latency metrics (golden signals F4/F5).
- Alert delivery channels.
