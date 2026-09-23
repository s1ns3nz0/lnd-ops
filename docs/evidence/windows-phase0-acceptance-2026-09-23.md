# Windows Phase 0 acceptance evidence (2026-09-23)

Host: Windows 11 Home, WSL 2 Ubuntu 24.04, amd64, single-node K3s v1.36.4+k3s1. No wallet password, seed, macaroon, invoice, payment hash, SCB bytes, backup passphrase, recovery key, or kubeconfig is included.

## Result

`ops/acceptance regtest` exited `0` on the existing funded regtest deployment without creating a wallet, payment, channel, backup, deployment, or other runtime mutation. Its terminal result reported:

```text
OK regtest acceptance: 2 wallets, 1 common active channel(s), recent bidirectional payments, 2 SCBs, monitoring and redeploy continuity
```

The final strengthened command wrote `${XDG_STATE_HOME:-$HOME/.local/state}/lnd-ops/evidence/regtest-acceptance-20260923T070419.049024Z.json` with mode `0600`. A structural scan found no seed, password, macaroon, passphrase, recovery-key, payment-request, or kubeconfig field. The result used schema `lnd-ops/regtest-acceptance/v1` and recorded all six checks as `pass`:

- unlocked wallets and identities;
- one common active positive-capacity channel;
- successful outgoing payments on each node correlated by hash with the other node's settled invoice within one hour;
- two current SCB backups with live source-hash equality;
- live LND and platform monitoring;
- current node, channel, LND PVC, SCB, cluster identity, Prometheus PVC, and exact historical Prometheus sample equality with passing wallet-preserving redeploy evidence from the preceding 24 hours.

The acceptance result also records the SHA-256 of the exact redeploy JSON it consumed, requires that source file to be operator-owned with mode `0600`, and confirms that the current regtest and monitoring Helm revisions equal the evidence's post-redeploy revisions (`4` and `3`). This binds the acceptance artifact to the checked redeploy record and detects later replacement.

The accepted SCB format was the documented temporary `gpg-symmetric-v1` path pending Windows Secure Boot and Device Encryption.

## Verification coverage

The Phase 0 implementation includes focused tests for a complete pass, a missing manual gate, a stale payment, unrelated payment/invoice hashes, stale redeploy evidence, current identity/storage mismatch, and malformed latest evidence. The repository verification adapter passed 22 Python tests, 19 Node tests, syntax checks, and the configured Helm lint/render matrix before the final Windows run.

## Workspace cleanup

After reviewing names, types, and sizes, the operator workspace removed only ten untracked troubleshooting artifacts: the bootstrap and repair logs, collector/regtest diagnostic logs, and two superseded temporary scripts. The cleanup did not include wallet data, SCBs, acceptance or redeploy evidence, PVCs, kubeconfig, or operator secret material. `git status --short` was empty afterward.
