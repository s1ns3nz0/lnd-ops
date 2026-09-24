# Windows Phase 4 Kubernetes security evidence

Validation completed: 2026-09-24 08:31:41 UTC  
Host: Windows 11 Home, WSL 2 Ubuntu, linux/amd64  
Tested Git revision: `0f13cc8463ef0c3aee9738fc43f1541f628360cc`

## Result

Phase 4 passed on the preserved testnet deployment. Kyverno enforced the
project admission rules, scoped workload identities had no mounted API token,
NetworkPolicy blocked an unauthorized probe, and a real Falco modern eBPF
event traversed Falcosidekick, Prometheus, and Alertmanager. The live LND TLS
certificate expiry metric and all Phase 3 dashboards remained available.

The run also created a replacement test-only payer after preserving a locked
payer PVC for a later recovery exercise. A private 30,000 sat channel reached
active state and settled fresh 10 sat payments in both directions. Both nodes'
SCBs were encrypted and verified outside their Kubernetes PVCs. The ordinary
redeployment then returned to the single operational node while retaining all
three LND PVCs.

The acceptance criteria are the Phase 4 exit check in the
[portfolio demo roadmap](../portfolio-demo-roadmap.md#phase-4-enforce-the-kubernetes-security-baseline).
The tested worktree was clean, and `ops/phase4-acceptance` recorded the Git
revision and Kubernetes context before writing its result.

## Test topology

| Resource | Role during the test | State after ordinary redeployment |
| --- | --- | --- |
| `lnd-0` / `data-lnd-0-0` | Original funded operational node | Running; PVC retained |
| `lnd-1` / `data-lnd-1-0` | Earlier test payer whose password was lost | Workload absent; recovery PVC retained |
| `lnd-2` / `data-lnd-2-0` | Replacement payer for fresh bidirectional payments | Workload absent; encrypted SCB and PVC retained |

The final Helm values describe the single operational node. The payer PVCs are
retained inputs for recovery and future test activity rather than members of
the ordinary running topology.

## Evidence

1. `ops/verify-security` allowed a compliant server-side dry-run and rejected
   fixtures with an unpinned image, missing resources, and privileged access.
2. The workload ServiceAccount could not read Secrets, had no automatically
   mounted projected API token volume, and used scoped RBAC. The negative
   authorization check was namespace-scoped `kubectl auth can-i get secrets`.
3. A disposable compliant Pod could not reach the protected LND RPC port under
   default-deny NetworkPolicy. The probe ran in the protected testnet namespace
   with the normal restricted workload context and attempted TCP port 10009.
   Documented DNS, Bitcoin testnet TCP 18333, Lightning TCP 9735, and monitoring
   scrape paths continued to operate.
4. Falco opened the syscall source with the modern BPF probe. A purpose-built
   process marker in the payment collector matched the project Falco test rule,
   appeared in Falcosidekick metrics, fired `LndOpsFalcoRuntimeEvent`, and was
   present in the Alertmanager API. This proves alert delivery into
   Alertmanager; no external notification receiver is claimed.
5. The live payment collector exported the LND certificate expiry timestamp.
   `LndOpsTLSCertificateExpiring` and the other 15 required rules evaluated
   with healthy evaluation state and linked to versioned runbooks. Alerts could
   be inactive or firing according to the live condition.
6. `ops/verify-dashboards` executed 57 PromQL expressions across six
   Git-provisioned dashboards and required a syntactically valid, nonempty live
   result for every panel.
7. `ops/redeploy-check` advanced the testnet release to revision 14 and the
   monitoring release to revision 10. It preserved the node identity, three
   channel records, LND and Prometheus PVC UIDs, current SCB, and an exact
   historical Prometheus sample.
8. `ops/phase3-acceptance` and `ops/phase4-acceptance` exited `0`. Their private
   machine-readable evidence files were created with owner-only permissions.

Kyverno and Falco were running as Helm release revision 2. Their installed Deployment
and DaemonSet images were digest pinned and the lock file had been verified for
linux/amd64 and linux/arm64 with `skopeo inspect --override-arch`. The public
digest mapping is in `ops/helm-plugins/lnd-ops-security-images/images.lock.json`.

`ops/backup-scb-encrypted` streamed each live SCB directly into GPG AES-256,
decrypted the new ciphertext in memory, and required the decrypted SHA-256 to
equal stable before/after hashes of the source. `ops/backup-status-encrypted`
then proved that the recorded plaintext hash still equaled the live SCB and
that the ciphertext and owner-only permissions were intact. This is backup
integrity evidence, not a restore exercise; isolated restore is a Phase 5 gate.

## Acceptance mapping

| Phase 4 requirement | Authoritative check |
| --- | --- |
| Allowed workload continues | `ops/verify testnet`, `ops/phase3-acceptance` |
| Kyverno positive and negative admission | `ops/verify-security` server-side dry-runs |
| Scoped RBAC and token isolation | `ops/verify-security` authorization and Pod-volume inspection |
| Network isolation | `ops/verify-security` disposable port-10009 probe |
| Runtime detection and alert path | Falco rule → Falcosidekick metric → Prometheus alert → Alertmanager API |
| Certificate handling | Live collector expiry timestamp plus `LndOpsTLSCertificateExpiring` evaluation |
| State-preserving reapplication | `ops/redeploy-check` before/after invariant comparison |
| Integrated final gate | `ops/phase4-acceptance` exit `0` and owner-only JSON |

## Commands

```sh
ops/backup-status-encrypted testnet lnd-0
ops/backup-status-encrypted testnet lnd-2
ops/redeploy-check
ops/verify testnet
ops/verify-security
ops/phase3-acceptance
ops/phase4-acceptance
```

The raw JSON remains outside Git under
`${XDG_STATE_HOME:-$HOME/.local/state}/lnd-ops/evidence/`. The corresponding
files are:

- `testnet-redeploy-20260924T082835.101043Z.json`
- `phase3-acceptance-20260924T083039.150411Z.json`
- `phase4-acceptance-20260924T083141.410973Z.json`

## Limitations

- Windows Secure Boot and Device Encryption remain deferred. Independent GPG
  encryption protects the off-PVC SCBs in the interim.
- Upstream LND images still run as root; seccomp, dropped capabilities,
  privilege escalation denial, RBAC, and network isolation constrain them.
- cert-manager is not installed because LND owns its self-signed RPC
  certificate. The deployment monitors expiry instead of introducing a second
  certificate authority for this boundary.
- The preserved `data-lnd-1-0` PVC requires seed-plus-SCB recovery because its
  test-only wallet password was lost. It remains stopped and is reserved for
  the isolated Phase 5 recovery exercise. Its seed and SCB are available; the
  recovery outcome has not yet been tested.
