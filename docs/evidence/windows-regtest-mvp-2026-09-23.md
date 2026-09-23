# Windows regtest functional MVP evidence (2026-09-23)

Host: Windows 11 Home, WSL 2 Ubuntu 24.04, amd64, single-node K3s v1.36.4+k3s1. This record contains no wallet password, seed, macaroon, invoice, payment hash, SCB bytes, encryption passphrase, recovery key, or kubeconfig.

## Functional result

- `ops/verify regtest` passed with both wallets unlocked and both node identities available.
- Bitcoin Core reported `regtest`, 113 blocks, and 113 headers, proving local regtest block generation.
- `ops/exercise-regtest` connected the two peers, retained one active 1,000,000 sat channel, and completed a fresh 10,000 sat payment in each direction.
- The final aggregate RPC check reported successful outgoing payments on both nodes: lnd-0 had 3 totaling 70,000 sat and lnd-1 had 2 totaling 20,000 sat. Settled incoming invoices existed on both nodes: lnd-0 had 2 totaling 20,000 sat and lnd-1 had 3 totaling 70,000 sat.
- `ops/verify-monitoring --profile regtest` passed Grafana, Prometheus 14-day retention, Alertmanager, Kubernetes and disk metrics, both LND scrapes, chain signal, and recent send/receive payment samples.

## SCB result

Windows Home did not expose Device Encryption because Secure Boot was disabled. The explicitly temporary encrypted-file workflow was used pending the documented Secure Boot and full-volume encryption follow-up.

- `ops/backup-scb-encrypted regtest lnd-0` and `lnd-1` streamed each SCB directly into a GPG AES-256 symmetric ciphertext without writing a plaintext host copy.
- Immediate decrypt-and-hash verification passed for both copies.
- `ops/backup-status-encrypted` subsequently matched each current LND SCB plaintext hash with its transfer record and matched each stored ciphertext hash. Recovery still requires the operator to retain the passphrase outside this repository and PC.

## Wallet-preserving redeployment result

`ops/redeploy-check regtest` passed and wrote its private machine-readable record to `${XDG_STATE_HOME:-$HOME/.local/state}/lnd-ops/evidence/regtest-redeploy-20260923T065045.540780Z.json`.

Before and after Helm chart reapplication, the verifier proved equality of:

- both LND public identities;
- the shared active channel point and channel list;
- both LND PVC UIDs;
- both current LND SCB plaintext hashes and encrypted host-copy integrity records;
- the Prometheus PVC UID;
- the cluster identity hash;
- one exact historical Prometheus series, timestamp, and value.

The regtest Helm revision advanced from 3 to 4 and the monitoring revision advanced from 2 to 3. After redeployment, both wallets remained unlocked, both nodes reported the same active 1,000,000 sat channel, both encrypted SCB checks passed again, and live monitoring verification passed.

## Deferred hardening

Enable UEFI Secure Boot and Windows Device Encryption, record the recovery key outside the host, then replace the temporary encrypted-file copies with the normal `ops/backup-scb` copies. This deferred host-hardening item does not change the demonstrated wallet, channel, payment, PVC, SCB-integrity, or Prometheus continuity results.
