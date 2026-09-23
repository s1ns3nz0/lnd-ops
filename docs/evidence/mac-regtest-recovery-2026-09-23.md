# Mac regtest seed and SCB recovery evidence (2026-09-23)

Host: macOS arm64 with Lima K3s. Network: disposable Bitcoin regtest.

1. The operator created and unlocked separate `lnd-0` and `lnd-1` wallets and retained their seeds outside the repository. `ops/verify regtest` passed.
2. `ops/exercise-regtest` opened a 1,000,000 sat channel and verified 10,000 sat payments in both directions. The channel point was `3ce5bb26614c00fa3ee46f69ccd89f9d48f5cc4584114fb71af121f35a9881c3:1`.
3. `ops/backup-scb` and `ops/backup-status` verified host copies for both nodes. The original `lnd-0` SCB SHA-256 was `ef3209348f8aeb8e4baa74697f4d5ba75898ebaef41db5af795b8ae1e02ed2cd`.
4. `ops/prepare-regtest-recovery --confirm-disposable` stopped original `lnd-0`, preserved PVC UID `dc34b155-7fb9-43d6-b799-b5ce523036d7`, created an isolated recovery PVC, and copied the verified SCB. The operator restored the original `lnd-0` seed interactively without exposing it to the repository or command line.
5. The recovered node returned the original public key `027bf70687a6f3bdf6e6b4a274c7390a9c71c6cc53a25b7988c12fcfd1ee289328`. Peer reconnection triggered Data Loss Protection. `lnd-1` force-closed the channel, the close and sweep confirmed on regtest, and the recovered confirmed balance increased from 999,834 to 1,943,058 sats.
6. `ops/verify-regtest-recovery` passed after the force-close CSV delay and sweep confirmations. It also verified the original PVC UID and the host/recovery SCB hashes.
7. `ops/finish-regtest-recovery --preserve-original-wallet` stopped and deleted the recovered copy before restarting the original identity. The recovery namespace disappeared and the original PVC retained UID `dc34b155-7fb9-43d6-b799-b5ce523036d7`. Interactive unlock of the restarted original wallet remains the next operator action.

No seed, wallet password, macaroon, wallet database, SCB contents, or payment request is included in this evidence.
