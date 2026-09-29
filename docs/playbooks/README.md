# Playbooks

A **playbook** guides judgment during an incident: what the impact is, how to
stop the bleeding, which evidence confirms which cause, what is allowed, and
when to escalate. A **runbook** is a fixed-step procedure for one task, such as
a deploy or a certificate rotation. A playbook may call a runbook.

Every playbook here uses the same sections:

1. Header: owner, last reviewed, alert, agent tools, related playbooks.
2. Impact and severity.
3. Mitigate first (stop the bleeding), including what needs approval.
4. Triage: which agent tool to call and which fields to read.
5. Diagnose: signal → likely cause → evidence.
6. Fix and verify: allowed actions, forbidden actions, pre-check → act → verify.
7. Escalate and communicate, with a customer message template.
8. When the agent can't help (`unknown`), and what the tools can't see.
9. Known gaps.
10. Worked examples, including tabletop exercises.

Review a playbook after every real incident or tabletop exercise that
contradicts it.

| Playbook | Entry signal |
|---|---|
| [opencti-paid-order-stuck](opencti-paid-order-stuck.md) | A paid order has no result |
| [opencti-l402-funnel](opencti-l402-funnel.md) | Aperture L402 payment gate verdict |

The older LND documents in `../runbooks/` are short playbooks too. They keep
that path because the live `get_versioned_runbook` tool serves them from it.
