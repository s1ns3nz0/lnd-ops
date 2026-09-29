# Runbooks (legacy path)

The files here are short **playbooks**: judgment documents for incidents, not
fixed-step runbooks. They sit under this legacy path for now.

Live alerts (`runbook:` annotations), the `get_versioned_runbook` tool,
`RUNBOOK_ALLOWLIST`, and the `runbook-agent-runbooks` ConfigMap all reference
these names and this path. Renaming any of them alone would break a running
system.

Plan: after the WSL rollout, move these files to `docs/playbooks/` and share one
`get_playbook` implementation. Until then, write new incident guides in
[../playbooks/](../playbooks/).
