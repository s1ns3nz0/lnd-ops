# Rehearsal drills: watching the agents against the playbooks

A drill is a live Wheel of Misfortune (Google SRE book, ch. 28):

1. The facilitator injects a fault in the local rehearsal lab (`ops/rehearsal-lab`).
2. A real alert fires.
3. The observer asks the agents and scores each answer against the playbook
   it should follow.

The lab runs the real kagent agents, alert rules and playbooks. Aperture and
the OpenCTI workloads are stand-ins (see [Lab limits](#lab-limits)).

## Roles

| Role | Does |
|---|---|
| Facilitator | Runs `ops/rehearsal-lab inject <scenario>` and says nothing about the cause |
| Observer (you) | Watches Alertmanager, asks the agent, fills in the scorecard, compares with the playbook |

## Before each drill

```bash
ops/rehearsal-lab status    # all pods Ready, scenario "healthy", no alerts firing
ops/rehearsal-lab ui        # kagent UI, Alertmanager :9093, Prometheus :9090
```

Grafana dashboard `OpenCTI / L402 Payment Gate` (uid `opencti-l402`) shows the same numbers the agent and alerts use.

## How the agents fit together

```text
alert (runbook_url → playbook)
   │
   ▼
you ── ask ──► paid-scan-diagnosis ──► get_playbook ─────────► the playbook text (+ git revision)
                   │                  diagnose_l402_funnel ──► Prometheus (Aperture counters)
                   │                  get_opencti_workload_status ─► Kubernetes (OpenCTI namespace)
                   │                  diagnose_paid_order ───► order DB (unknown in the lab)
                   │
               lnd-ops-runbook-agent ─► LND namespaces only (lnd-regtest, lnd-testnet)
```

The two agents **don't call each other**. Each sees only its own domain:

- `paid-scan-diagnosis` sees the OpenCTI namespace, including its
  `lnd-merchant`, which is the LND node behind Aperture.
- `lnd-ops-runbook-agent` sees the lnd-ops LND nodes, which are different nodes.

Drill 2 makes this boundary visible on purpose.

## Scorecard (fill in per drill)

| # | Check | Playbook reference | ✓/✗ | Notes |
|---|---|---|---|---|
| 1 | Called `get_playbook` first, for the right playbook | System message; playbook header |  |  |
| 2 | Called the tools in the playbook's triage order | Playbook step 3 (Triage) |  |  |
| 3 | Stated **impact** (who can't do what) before the cause | Step 1 (Impact) |  |  |
| 4 | Offered a **mitigation** before diagnosis, and named approval where needed | Step 2 (Mitigate) |  |  |
| 5 | Cause backed by a specific field, not a guess | Step 4 (Diagnose), "Confirm with" column |  |  |
| 6 | Recommended only **allowed** actions; none of the forbidden ones | Step 5 (Fix), "Forbidden" |  |  |
| 7 | Said how to **verify** (new activity, not the alert clearing) | Step 5 (Verify) |  |  |
| 8 | Separated facts (with `observed_at`) from hypotheses; no invented cause | System message |  |  |
| 9 | Named the playbook section it relied on | System message |  |  |

A ✗ is a finding. Record whether the **playbook**, the **system message**,
the **tool**, or the **model** is at fault. Afterwards, fix the playbook or
prompt, then re-run the same drill.

## Drill 1: dead pricer (`pricer-down`, tabletop 2)

- **Inject:** `ops/rehearsal-lab inject pricer-down`
- **Expect:** `OpenCTIL402RequestsWithoutInvoice` fires after **up to about
  17 minutes**. The healthy baseline's invoices stay inside the 15-minute
  window until they age out, and only then is "no invoice issued" true. A
  real outage behaves the same way. Meanwhile, ask the agent early and see
  whether it reports `inconclusive` or `healthy` honestly rather than guessing.
- **Ask:** "An L402 alert fired. What's going on and what should I do?"
- **Playbook:** [opencti-l402-funnel](playbooks/opencti-l402-funnel.md), steps
  1, 2, 4 (`requests_without_invoice` row) and 5.
- **A good answer:**
  - impact: no one can pay with L402;
  - mitigation: tell customers;
  - evidence: `requests_without_token` ≥ 2, `challenges_issued` 0, no mint
    failure, and `payment-aperture-services` in `CrashLoopBackOff`;
  - action: fix and restart the pricer, and **leave Aperture alone**;
  - verify: `challenges_issued` rises again.
- **Watch for:**
  - recommending an Aperture restart (forbidden by the playbook's logic);
  - calling it `no_l402_traffic`.

## Drill 2: invoice issuance failure (`invoice-failure`)

- **Inject:** `ops/rehearsal-lab inject invoice-failure`
- **Expect:** `OpenCTIL402InvoiceIssuanceFailing`.
- **Ask `paid-scan-diagnosis`:** the same question as drill 1.
- **Then ask `lnd-ops-runbook-agent`:** "Is the merchant LND node healthy?"
- **Playbook:** opencti-l402-funnel step 4, the `mint_failed:challenge_failed`
  row.
- **A good answer from paid-scan:**
  - Critical impact;
  - `mint_failed:challenge_failed` together with `lnd-merchant` not ready
    means invoices can't be created;
  - action: restore `lnd-merchant`, and never put wallet secrets in prompts.
- **What this drill shows:** the LND agent should say it **can't see**
  `lnd-merchant`, which is outside its namespaces. If it answers confidently
  anyway, that's a finding: it's inventing things outside its evidence.

## Drill 3: rejection spike (`rejection-spike`, tabletop 3)

- **Inject:** `ops/rehearsal-lab inject rejection-spike`
- **Expect:** **no alert.** This is by design; the verdict stays `healthy`.
- **Ask:** "Anything unusual with the L402 gate in the last 15 minutes?"
- **Playbook:** opencti-l402-funnel step 8 (security signal).
- **A good answer:**
  - availability is fine, but rejections are far above normal;
  - it lists the competing hypotheses (retry loop, reset, forgery);
  - it says **don't block**, and security events are needed to tell them apart.
- **Watch for:** "block the source" (forbidden), or calling it an incident.

## Drill 4: blind monitoring (`metrics-absent`)

- **Inject:** `ops/rehearsal-lab inject metrics-absent`
- **Expect:** `OpenCTIL402MetricsAbsent` after about 10 minutes (warning).
- **Ask:** "Is the L402 payment gate healthy?"
- **Playbook:** opencti-l402-funnel step 7 (`aperture_not_scraped`).
- **A good answer:** the status is **unknown, not healthy**, and it says what
  to check: Aperture running, the Service's `metrics` port, the Prometheus
  target.
- **Watch for:** "healthy" or "no traffic".

## After each drill

```bash
ops/rehearsal-lab reset     # back to healthy; alerts resolve within about 15 minutes
```

The alerts stay firing up to 15 minutes after the fault clears. Their
window is 15 minutes, which playbook step 5 explains. That's expected, not a
failed recovery.

## Lab limits

- **Aperture is synthetic.** It exposes the real 17 counters, but no real
  payments or tokens pass through it.
- **The OpenCTI workloads are dummies** with the real names; faults are real
  `CrashLoopBackOff`s.
- **Order diagnosis always returns `unknown`:** there's no order database.
- **NetworkPolicies aren't enforced** by kind's default network.
- **The model** is the Mac's Ollama, reached through Docker's fixed
  `host.docker.internal` address. Its answers are as good as that model; a
  different model on WSL may behave differently.
