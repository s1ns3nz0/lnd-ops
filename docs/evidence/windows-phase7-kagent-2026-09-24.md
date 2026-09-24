# Windows Phase 7 constrained kagent evidence

Date: 2026-09-24  
Host: Windows 11 Home, WSL 2 Ubuntu, K3s linux/amd64  
Ollama server: separate LAN endpoint on Mac arm64  
Model: `gpt-oss:20b`  
Exercise revision: `f331e41add0381c8b9e520e1d91ccc59617ac73e`
Acceptance revision: `f331e41add0381c8b9e520e1d91ccc59617ac73e`

## Result

Phase 7 passed on the Windows cluster. kagent `0.9.12` used the configured
external Ollama server and the project's constrained MCP gateway. The Agent and
RemoteMCPServer both reported `Accepted=True`; the Agent also reported
`Ready=True`. kagent discovered exactly these six project tools:

- `get_workload_status`
- `get_redacted_logs`
- `diagnose_incident`
- `get_versioned_runbook`
- `verify_health`
- `execute_allowlisted_response`

The upstream generic Kubernetes tool server and bundled agents were disabled.
The runbook Agent Pod used a token-free ServiceAccount. Only the gateway held a
Kubernetes token with namespace Roles.

## Live diagnosis

`ops/exercise-phase7-agent` first saved the exact regtest peer NetworkPolicy,
denied ingress and egress, and disconnected the one active channel. The
gateway observed the real inactive-channel signal at 11:40:17 UTC. While that
fault was active, the exercise invoked the real kagent Agent through a local
controller port-forward. The model called `diagnose_incident` with the fixed
`channel_inactive` scenario, received `signal_active=true`, and read
`channel-inactive.md` through the MCP gateway. Its completed response contained
all required fields:

1. Observed facts
2. Likely cause
3. Confidence
4. Matching runbook
5. Recommended command
6. Automation eligibility

The exact NetworkPolicy was restored in a `finally` path, its canonical SHA256
was identical before and after, the peer reconnected, the channel returned
active, and the gateway signal returned healthy at 11:41:02 UTC. The exercise
stored the complete response privately with mode `0600`. Public
evidence records only its SHA256 digest and contract checks; it contains no
invoice, payment hash, preimage, macaroon, wallet password, or seed.

## Response policy proof

The same exercise then used the deterministic gateway path:

| Check | Observed result |
| --- | --- |
| Restart dedicated stateless diagnostic probe | Allowed; rollout returned Ready |
| Audit for allowed restart | `RunbookActionAllowed` Kubernetes Event created |
| Immediate repeated restart | Denied by the five-minute cooldown |
| `unlock_wallet` request | Denied because it is absent from the action allowlist |
| Audit for denied requests | `RunbookActionDenied` Kubernetes Events created |

`ops/phase7-acceptance` independently used Kubernetes authorization review to
prove that the gateway cannot create or delete Pods, patch either LND
StatefulSet, patch the testnet PVC, create Secrets, or patch NetworkPolicies.
It can patch only the named `runbook-diagnostic-probe` Deployment for its one
mutation. The gate also verified the accepted MCP server, available gateway and
probe Deployments, the Phase 6 ancestor evidence, and the live exercise record.

## Reproducibility and artifacts

The repository vendors the kagent and kagent CRD `0.9.12` charts with checked
SHA256 hashes. Controller, Agent runtime, skills initializer, UI, and PostgreSQL
images are pinned to multi-architecture OCI index digests. `ops/deploy-agent`
validates `/api/tags` and the selected model before cluster changes, discovers
the actual K3s API EndpointSlice for a narrow egress rule, and can be rerun with
the owner-only saved endpoint configuration. A second deployment succeeded
after the cooldown runtime ConfigMap was separated from Helm ownership.

Private evidence:

- `phase7-exercise-20260924T114012.974152Z.json`, mode `0600`, SHA256
  `59d302950af083007241a4fd7aa1161f4e788c34aaa6d4110f970ed5415909eb`
- `phase7-acceptance-20260924T114111.327656Z.json`, mode `0600`, SHA256
  `f50db9d6b4cf6d2405af9e57eaef3bc0b915d0f0c755a0f0b191a81455ff46cb`

## Limitations

The exercised Ollama endpoint used explicitly acknowledged HTTP on the trusted
home LAN. The endpoint was constrained by the kagent namespace egress policy to
one `/32` server address and one port, but transport encryption was absent.
Replace it with an HTTPS reverse proxy or VPN before moving beyond the private
network. Native Ollama in this pinned kagent release supplies no API credential,
so server-side source filtering remains required.

kagent's controller uses its upstream unsecure mode. It and the UI are
ClusterIP-only, namespace ingress is restricted, and operator access uses a
local `kubectl port-forward`; this is suitable for the single-operator demo,
not a multi-user control plane. Windows full-volume encryption remains the
previously declared deferred host-hardening item.
