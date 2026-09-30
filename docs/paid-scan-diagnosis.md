# Paid order diagnosis

The first slice locates where one paid-scan order is waiting: payment, scan creation, dispatch, worker start, running scan or result persistence. `diagnose_paid_order` requires canonical UUID `tenant_id` and `order_id`. It reads a backend projection and returns typed database facts, their observation time, a next check and explicit limitations. A waiting stage is not a declared outage.

## Implementation status

The MCP client, dedicated kagent Agent and optional Helm resources are implemented in this repository. The OpenCTI backend projection is a proposed integration contract, not an existing endpoint. No live order, WSL deployment, model invocation or SIEM correlation has been verified. The feature is disabled by default. The existing runbook Agent and its probe-restart tool are unchanged; the separate `paid-scan-diagnosis` Agent has only the new read-only tool.

## Backend contract

Implement `GET /internal/v1/diagnostics/tenants/{tenant_id}/orders/{order_id}` on the private OpenCTI backend, through HTTPS. Require a dedicated diagnostic bearer credential with a server-side tenant allowlist. Do not reuse a workspace, payment, LND or dispatcher credential. Enforce tenant authorization before data access and return the same 404 for invisible and nonexistent orders. Reject duplicate authentication headers, query parameters and request bodies. Perform a read-only consistent database snapshot; the endpoint must not reconcile payments or dispatch work.

Return `Content-Type: application/json` and `Cache-Control: no-store`. The minimal version-1 response below uses synthetic IDs. All shown fields are required except `dispatch.updated_at`; `scan`, `dispatch` and `payment.challenge` may explicitly be null. Missing required fields are unknown evidence, not evidence of an absent scan.

```json
{
  "schema_version": 1,
  "source": "tenant_database",
  "observed_at": "2026-09-27T10:00:00Z",
  "tenant_id": "11111111-1111-4111-8111-111111111111",
  "order": {"id": "22222222-2222-4222-8222-222222222222", "state": "paid"},
  "payment": {
    "rail": "l402",
    "challenge": {"state": "settled"},
    "event_recorded": true,
    "receipt_commit_state": "committed"
  },
  "scan": {"state": "queued", "result_available_at": null},
  "dispatch": {"state": "pending", "updated_at": "2026-09-27T09:58:00Z"}
}
```

State values follow the inspected OpenCTI database schema; the client allowlists are in [paid_scan_diagnostics.py](../agent/paid_scan_diagnostics.py). Payment rail is `l402` or `x402`; receipt commit state is `pending`, `committed` or null. Timestamp fields are UTC ISO-8601 strings ending in `Z`. `observed_at` is the database snapshot time, not the invoice settlement time. Observations older than 30 seconds or more than five seconds in the future are rejected. Future result/dispatch timestamps are rejected with the same five-second tolerance.

An order marked paid with no payment event is inconsistent evidence. A paid order with a pending receipt commit or a present, non-settled challenge needs payment-record review before scan-stage diagnosis. These checks do not declare a failed payment. `registered` means dispatch registration and directs inspection to the dispatcher; `dispatched` directs inspection to worker start. Neither is independent proof that a Kubernetes Job exists.

The client does not expose arbitrary upstream fields, raw errors, invoices, hashes, receipts, scan findings or credentials. Failure reasons are restricted to `FAILURE_REASONS` in the client. It accepts at most 32 KiB, does not follow redirects or environment proxies, and issues only GET requests to an operator-configured HTTPS origin. Failed lookup, invalid schema, inaccessible tenant and stale evidence produce `status: unknown`. MCP `/healthz` reports process readiness only, never upstream health.

## Deployment prerequisites

Before enabling, implement and test the private projection in OpenCTI, provision its dedicated read-only credential and TLS trust, and permit ingress from the gateway's namespace/pod selector. The endpoint's certificate must match its service hostname. Existing MVP fixtures are not proof of WSL compatibility.

Use reviewed values with `ops/deploy-agent --agent-values <values-file>` alongside the existing Ollama configuration. Set `paidScan.enabled`, `origin`, backend `namespace`, `podLabels`, `port`, and `credentialSecret`; see [chart defaults](../charts/agent/values.yaml). The pre-existing Secret in `lndops-agent` must contain `token` and `ca.crt`. Secrets are not created by the chart. The Agent is pinned to the self-hosted Ollama `default-model-config` installed by `ops/deploy-agent` (tenant data must not reach other models); the gateway itself never connects to Ollama.

The gateway mounts its own service-account token (`paid-scan-diagnostics`) solely for `get_opencti_workload_status`; see Slice 2 below. Its egress allows DNS, the selected backend pods/port and the Kubernetes API (`kubeApi.serverCIDR`/`port`). MCP ingress permits the kagent namespace; this trusts that namespace and is not end-user authentication. Backend credentials enforce tenant scope independently. Existing namespace policies may add permissions because Kubernetes NetworkPolicies are additive.

## Delivery plan

Decisions agreed on 2026-09-29:

- Scope: one operator (the repository owner) asks the Agent manually through `kubectl port-forward`. No alert-triggered runs.
- Placement: kagent and OpenCTI share the WSL k3s cluster in separate namespaces; the diagnostic endpoint is their only link.
- Endpoint: a separate OpenCTI `diagnostics_app` listener, not the payment-network `internal_app`. Its NetworkPolicy admits `lndops-agent` only.
- Model: self-hosted Ollama only. Tool output contains tenant data and must not reach an external LLM API.
- Credentials: `ops/provision-paid-scan-diagnostics` creates a self-signed CA, a server certificate and a random token. OpenCTI stores the token's sha256 hash and an E2E-only tenant allowlist. Rotation re-runs the script and accepts a brief restart.
- Ownership: client and Agent stay in this repository; the contract test lives in OpenCTI. Move to a separate chart when a second OpenCTI tool appears.

Slices:

1. Database stages only (this document's contract).
2. Job, Pod and Event reads in the OpenCTI namespace. No `pods/log`, because scanner logs can contain customer target data.
3. A read-only list of paid orders stuck longer than a threshold, per stage. This is the first metric candidate.

Slice 1 acceptance on the WSL E2E namespace:

| Setup | Expected answer |
|---|---|
| Completed Basic x402 order | Results persisted, with timestamps |
| Dispatcher scaled to 0, then a new paid order | Dispatch pending; next check is the dispatcher |
| Random UUID or another tenant's order | `unknown`, same 404 for both |
| Wrong token or endpoint down | `unknown`, never healthy |

## Slice 1b: optional projection fields

The endpoint may add `scan.failure_reason`, `dispatch.reason` and `dispatch.job_name` (each string or null; `schema_version` stays 1). Older servers omit them and the client reports null. Reasons must match `^[a-z][a-z0-9_]{0,63}$` and job names `^scan-[0-9a-f]{20}$`; anything else is `invalid_response`. They appear as `scan_failure_reason`, `dispatch_reason` and `dispatch_job_name` in `observed_facts`. For `worker_start`, `scan_running` and `scan_terminal_without_result` with a job name, `next_check` points to `get_opencti_workload_status`.

## Slice 2: `get_opencti_workload_status`

Takes no arguments. Reads, in the `OPENCTI_NAMESPACE` (`paidScan.namespace`) only and with GET, Deployments, Jobs labelled `app.kubernetes.io/name=scanner-worker` (newest 20), non-Succeeded Pods (max 50) and Warning Events (newest 30), using the pod's service-account token with TLS verification, a 5 s timeout and a 1 MiB cap. Output is allowlisted: Deployment replica/availability, Job counters/condition/times, Pod phase/owner/container states and restart counts, and Event reason/object/count/time. Event `message`, annotations, env and logs are never returned. Reason strings not matching `^[A-Za-z][A-Za-z0-9]{0,63}$` become `Other`; items with invalid names are dropped. Any failure returns `{"status":"unknown","reason":<fixed code>}`, with `kubernetes_unavailable` added for API errors. Kubernetes state is not proof of backend completion, and Warning events expire (default 1h).

RBAC: Role `paid-scan-workload-reader` in the OpenCTI namespace grants get/list on `deployments`, `jobs`, `pods` and `events` only (no `pods/log`, secrets or watch), bound to ServiceAccount `paid-scan-diagnostics` in the release namespace. The pod sets `automountServiceAccountToken: true`.

Status: implemented and unit/chart-tested; not live-verified against a cluster.

## Slice 3: `diagnose_l402_funnel`

Takes no arguments. Runs nine fixed instant queries (GET `/api/v1/query`, `PROMETHEUS_URL`, default the monitoring Prometheus service; 5 s timeout, 256 KiB cap) over a 15m window against the `aperture` job: `up`, mint `ok`/failed by result, and verify `accepted`, `invoice_state_mismatch`, `secret_store_error` and rejected by reason. `credential_verified` is never queried (it is nested in `accepted`). Empty vectors count as 0; increases are rounded and clamped at 0; labels outside the allowlists become `other`.

Verdict: `incident` on any mint failure or `secret_store_error`; `no_l402_traffic` when nothing was minted, accepted, unsettled or rejected; otherwise `healthy`. Output carries `scope: "l402"`: Aperture metrics cover the L402 scheme only, so MPP and the x402 rail are not counted and `no_l402_traffic` does not mean no payments. Rejections set `security_signal` only (`none`, `present`, or `elevated` when at least 20 and 10x the previous-24h per-15m average, `rejected_baseline_per_15m`) and never change the verdict. Any Prometheus/shape error gives `unknown` + `prometheus_unavailable`; an empty or zero `up` gives `unknown` + `aperture_not_scraped`. No partial data is returned.

Requires the new `aperture` scrape job in [monitoring-values.yaml](../charts/monitoring-values.yaml) (service `l402-aperture`, port name `metrics`, namespace `opencti-paid-scan-e2e`) and the Aperture metrics build referenced below. The NetworkPolicy allows egress to `lndops-monitoring:9090`.

Status: implemented and unit/chart-tested; the scrape job and tool are not live-verified against a cluster.

## Remaining integration

After the first projection is connected, add bounded Job/Pod evidence and structured Aperture events. Keep each source's timestamp and availability separate. Database payment state does not independently prove current LND settlement; `scan.state=completed` does not prove customer result retrieval.

The reviewed Aperture [security-event branch at 239bba69](https://github.com/s1ns3nz0/aperture/blob/239bba69f884b878b0ce22523b0b8e961bb8dd72/docs/security-events.md) and [L402 metric changes at 78cacdd0](https://github.com/s1ns3nz0/aperture/blob/78cacdd05c673312bfb80d4efcd96e015a9a12c7/mint/metrics.go) are separate histories. A combined, tested deployment is needed for both. Do not sum `credential_verified` and `accepted` as distinct requests. Authentication success does not prove backend completion, and `invoice_state_mismatch` can include invoice lookup errors. Security events require external collection; output counters do not acknowledge SIEM delivery. HMAC `payment_ref` cannot be directly joined to a raw payment hash; that join needs a trusted reference projection. No such join exists in this slice.

## Agent evaluation harness

Checks the agent's reasoning, not the tools, against fixed scenarios with no production data and no production agent. `paidScan.eval.enabled=true` adds a credential-free `paid-scan-eval-fixture` (same tool schemas, canned outputs, real `get_playbook`, DNS-only egress), a `paid-scan-eval` RemoteMCPServer and a `paid-scan-diagnosis-eval` Agent. Both Agents render the same `systemMessage` from one Helm helper, so the prompt cannot drift.

Scenarios are the source of truth in [tests/eval/scenarios](../tests/eval/scenarios) (`question`, canned `tools`, `expect`); `ops/deploy-agent` ships them as ConfigMap `paid-scan-eval-scenarios`. Run after `ops/deploy-agent` with the chart values enabled:

    ops/eval-paid-scan-agent --runs 3 [--scenario NAME ...] [--out DIR] [--min-pass 0.667]

Each run sets `/state/active` in the fixture, invokes the eval Agent through kagent, grades the answer and writes 0600 evidence JSON. The exit code is non-zero if any scenario's pass rate is below `--min-pass`.

### Eval results

Rehearsal lab, `gpt-oss:20b`, 5 scenarios. Scores use the grader as of each
row; "re-graded" rows re-score saved answers after a grader fix.

| Commit | Change under test | Runs | Pass rate |
|---|---|---|---|
| before `7cdba51` | Baseline prompt | 3 per scenario | 7/15 (47%) |
| `30ba748` | Playbook-first prompt, workload tool rule | 3 | 9/15 (60%) |
| `d3c41a4` | Components list, x402-only, timing facts in the funnel playbook | 5 | 17/25 (68%) |
| `15898d1` | Scan-path components in the order playbook | 5 | 19/25 (76%); re-graded 20/25 (80%) |
| `44e3745` | Prompt rule: name workloads exactly | 5 | 17/25 (68%); re-graded 18/25 (72%). Reverted |
| `b5c4d0a` | Tool output carries `components_to_check` and `escalation` | 5 | 18/25 (72%) |

The L402 scenarios pass reliably. The order scenarios still fail mostly on
invented component names (`postgres-pod`, `scan-worker`) when evidence is
missing, so a human reviews every answer. Prompt rules had no measurable
effect at this model size; facts in tool output helped (escalation mentions
went from failing to passing).

Grading checks required tool calls, the expected playbook read, any-of `must_mention` groups and `must_not` regexes. A `must_not` match is ignored when a negation cue (never, not, no, avoid, forbidden, n't) is within 6 words before it in the same sentence, or a prohibition cue within 4 words after. This is a heuristic: it misses distant cues and paraphrases, and can excuse a real recommendation that follows an unrelated "not". Treat a pass as weak evidence and read failing answers. The final-answer extraction (artifacts, else the last text message) has not been checked against live kagent output. Not live-verified; the unit tests use canned invocations.

## Verification

Run `python3 -m unittest discover -s tests -p test_paid_scan_diagnostics.py`. CI repeats these transport, schema, diagnosis and real HTTP MCP tests in digest-pinned Linux Python and lints the enabled Helm configuration. Tests use synthetic order responses; they do not establish real payment settlement or live service readiness.
