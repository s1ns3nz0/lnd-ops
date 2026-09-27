# Router external encrypted SCB copy

In Router progress, choose **o → 4** to create and locally decrypt-check the current
testnet SCB using the existing encrypted backup workflow. Keep the seed and the
encryption passphrase separately. Manually transfer the resulting
`~/lnd-ops-backups-encrypted/testnet/lnd-0/channel.backup.gpg` to another device or
external storage. The workflow does not upload files or store remote credentials.

Choose **o → 7**, enter the path to that mounted external file, and confirm that
it is stored outside this PC. The checker reads it and compares its ciphertext
hash with the current local encrypted backup. Before and after that read, it
checks the current node identity and verifies the local backup record against the
live SCB hash. The read-only backup check does not update Kubernetes ConfigMaps.
The current host backup file, a hardlink to it, symlinks, special files, empty
files and files larger than 64 MiB are rejected.

The file's external location is **operator-attested**. A matching hash cannot
prove that storage is on another device; another folder on the same PC is not an
external copy. A separate regular file is accepted after you attest that its
storage is outside this PC. Nothing here independently certifies the storage provider.

Choose **o → 8** to recheck the registered copy. Missing or inaccessible storage,
changed ciphertext, a changed node identity, or a changed SCB makes it unverified.
After opening or closing channels, recreate the encrypted backup, transfer the
new file, and register it again. Do not interpret a previously successful record
as proof that the current channel set is protected. Status does not automatically
mount storage, transfer files or update the registration.

Registration saves only the path, public node key, hashes, timestamps and location
attestation in the private Router state file `backup-copy.json`. It does not save
the ciphertext, seed, password or macaroon there. The external copy check never
decrypts or restores a wallet. `restore_tested` is always false: password recovery,
seed storage and an isolated recovery exercise remain separate requirements.

The same operations are available as `ops/router-backup-copy` (interactive) and
`ops/router-backup-copy --status --json` (read-only). Status exits 0 only for a
currently matching copy and 10 when unverified or missing. These commands target
the existing first testnet node and do not mark a Phase complete.
Expected file, permission, RPC and timeout errors return the unverified state
with exit 10. Invalid command arguments exit 2. Unexpected process failures must
also be treated as failure, never as successful backup verification.
