# Encrypted SCB stale or mismatched

## Trigger

`LndOpsSCBBackupStale` fires when a live SCB exists but the latest encrypted backup record is older than 24 hours or its recorded plaintext hash differs from the live SCB for five minutes.

## Diagnose

1. Run `ops/backup-status-encrypted <profile> <node>` from the operator host.
2. Confirm the live SCB exists, the ciphertext and transfer record are operator-owned mode `0600`, and parent directories are mode `0700`.
3. Determine whether a channel open/close or Pod restart regenerated the SCB after the last backup.
4. Never print SCB bytes, the seed, wallet password, or encryption passphrase.

## Recover

Run `ops/backup-scb-encrypted <profile> <node>` interactively and enter the operator-held passphrase. Confirm `ops/backup-status-encrypted` succeeds and the dashboard reports current. Recovery testing remains an isolated manual exercise; never start a second copy of the active identity.
