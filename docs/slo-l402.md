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
| **Component health probe** | Prometheus blackbox exporter, job `l402-probe`, every 60 s, three targets labelled `component`: `pricer` = `GET http://payment-aperture-services:8090/health` expects 200; `lnd_merchant` = `GET https://lnd-merchant:8080/v1/state` (unauthenticated) expects body `SERVER_ACTIVE`; `aperture` = TCP connect to `l402-aperture:8081`. The SLI is **all three succeed** (`min`) | **Alerting** (fast, traffic-independent) |
| Real-traffic invoice success | `aperture_l402_mint_total{result="ok"}` / `aperture_l402_verify_total{reason="missing_credentials"}` | **SLO reporting** only (too noisy to alert on at low traffic) |

**Why not an end-to-end invoice probe:** the pricer only prices real orders.
`GetPrice` requires a valid `/paid/l402/<tenant>/<order>/<hash>/<id>` path, gateway
authentication, a workspace credential and an order-database lookup. A probe that
reaches invoice creation therefore needs a permanent synthetic "canary order" in
OpenCTI, which is product work (future). **Known gap:** every component can be
healthy while invoices still aren't issued (for example config or authentication
errors). The existing counter alerts cover that gap, more slowly.

Recording rules (names shared by alerts and the agent tool):

- `l402_probe:up` = `min(probe_success{job="l402-probe"})`
- `l402_probe:error_ratio_5m|30m|1h|6h` = `1 - avg_over_time(l402_probe:up[<w>])`

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

## Probe side effects

None. Health endpoints create no invoices, orders or database rows.

## Agent

`diagnose_l402_funnel` adds `probe_components` (last result per component),
`probe_success_1h`, `slo_burn_rate_1h` and `slo_burn_rate_5m` from fixed PromQL. `unknown` applies when the probe isn't
scraped. The playbook's timing facts are updated from the next rehearsal
measurement.

## Lab

The dummy `payment-aperture-services` serves `/health`, the dummy `lnd-merchant`
serves `/v1/state` over TLS, and the synthetic `l402-aperture` listens on 8081.
A crash-looping workload refuses connections, so `pricer-down` and
`invoice-failure` fail the probe naturally. The blackbox exporter and the probe scrape job run in the
lab like in production. Success means scenario 1's detection time is
measured and compared with the 16-minute baseline.

## Out of scope

- Aperture HTTP status and latency metrics (golden signals F4/F5).
- Alert delivery channels.
