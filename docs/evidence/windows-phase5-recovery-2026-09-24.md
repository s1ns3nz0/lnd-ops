# Windows Phase 5 backup and recovery evidence

Validation completed: 2026-09-24 10:05:41 UTC  
Host: Windows 11 Home, WSL 2 Ubuntu, linux/amd64  
Runtime-tested Git revision: `0d34328`

## Result

Phase 5 passed on the local Windows portfolio cluster; no production resources
were involved. The Windows checkout was clean at revision `0d34328` when the
integrated acceptance gate ran. A disposable regtest identity opened a
channel, completed payments in both directions, and produced independently
encrypted SCBs for both nodes. The original `lnd-0` StatefulSet was then
stopped while its PVC remained bound. A fresh PVC in an isolated namespace
restored the same identity from the operator-held aezeed and encrypted SCB.

The recovered node connected to its peer, triggered LND data-loss protection,
and caused the peer to force close the channel. After the CSV delay and sweep
confirmation, the peer recorded the closed channel and the recovered wallet's
confirmed on-chain balance increased from 999,834 sat to 1,942,225 sat. The recovered copy was stopped and
deleted before the preserved original PVC was restarted.

The five-minute alert rule used by the production-shaped chart was exercised in
this local cluster. A temporary
missing status record caused `LndOpsSCBBackupStale` to fire and reach
Alertmanager. The command restored the original record in its cleanup path and
confirmed that the live freshness metric returned healthy. Backup bytes were
not modified by this fault.

`ops/phase5-acceptance --acknowledge-host-encryption-deferred` passed after
fresh testnet payments and a new wallet-preserving redeployment proof. It also
reran the Phase 4 security and dashboard continuity gates.

## Acceptance mapping

| Phase 5 requirement | Authoritative proof |
| --- | --- |
| Encrypted SCB integrity | Recovery record fields `scb_format` and `scb_integrity`; the verifier also matched the transfer record, ciphertext, and recovery-Pod plaintext hash before writing the pass result |
| Isolated recovery | Recovery fields `original_identity_stopped` and `original_pvc_uid`; the recovery namespace used a distinct PVC |
| Identity continuity | `recovered_identity_pubkey`; the verifier required equality with the identity captured before original shutdown |
| LND data-loss protection | `peer_recorded_close` and `closed_channel_point`; runtime logs recorded restored-channel DLP before the peer force close |
| Funds returned on-chain | `confirmed_balance_before_sat`, `confirmed_balance_after_sat`, and `recovered_funds_increased`; observed 999,834 → 1,942,225 sat |
| Duplicate identity prevention | The finish command scaled the recovered StatefulSet to zero and deleted its namespace before scaling the original to one; acceptance required the recovery namespace to be absent |
| Backup alert and recovery | Alert fields `alertmanager_observed` and `restored_current_metric`; this proves delivery and source-metric recovery without claiming an external notification receiver |
| Earlier-phase continuity | The redeploy record preserved identity, channels, PVCs, SCB, and a historical Prometheus sample; the Phase 4 record reran dashboards, Kyverno, RBAC, NetworkPolicy, Falco, and TLS gates |

## Commands

```sh
ops/create-regtest-wallet lnd-0
ops/create-regtest-wallet lnd-1
ops/exercise-regtest
ops/backup-scb-encrypted regtest lnd-0
ops/backup-scb-encrypted regtest lnd-1
ops/prepare-regtest-recovery --confirm-disposable
ops/verify-regtest-recovery
ops/finish-regtest-recovery --preserve-original-wallet
ops/exercise-backup-alert
ops/redeploy-check
ops/phase5-acceptance --acknowledge-host-encryption-deferred
```

Private machine-readable records remain outside Git under
`${XDG_STATE_HOME:-$HOME/.local/state}/lnd-ops/evidence/` with mode `0600`.
They can be inspected with `python3 -m json.tool FILE`; the acceptance scripts
reject an unexpected schema, result, owner, or mode. The final gate used:

| Record | Schema or role |
| --- | --- |
| `regtest-recovery-20260924T095536.491575Z.json` | `lnd-ops/regtest-recovery/v1` |
| `backup-alert-exercise-20260924T085244.900295Z.json` | `lnd-ops/backup-alert-exercise/v1` |
| `testnet-redeploy-20260924T100418.448857Z.json` | Latest wallet-preserving redeploy proof |
| `phase4-acceptance-20260924T100541.329411Z.json` | Phase 4 continuity result |
| `phase5-acceptance-20260924T100541.340450Z.json` | `lnd-ops/phase5-acceptance/v1` |

## Operational improvements made during the exercise

- Internal LND peer traffic now permits TCP 9735 in both ingress and egress
  directions under the default-deny policy.
- The isolated recovery namespace permits only the Bitcoin RPC/ZMQ and peer P2P
  egress needed for recovery.
- Bitcoin Core runs as its non-root image user while retaining PVC access.
- `ops/abort-regtest-recovery --preserve-original-wallet` safely retires a
  failed recovery attempt after matching the recorded original PVC UID.
- `ops/create-regtest-wallet` labels wallet passwords, aezeeds, optional aezeed
  cipher passphrases, and SCB GPG passphrases by role before interactive input.

## Limitations

- Windows Device Encryption remains explicitly deferred by the operator because
  it is unavailable on this host. AES-256 GPG encryption protects the off-PVC
  SCBs in the interim. This exception covers the portfolio test environment
  only, provides no full-volume protection, and must be closed before claiming
  production readiness or storing mainnet funds.
- The recovery used disposable regtest funds. It proves the mechanism and
  operator workflow without risking testnet funds.
- Raw recovery evidence is host-local and is intentionally excluded from Git.
