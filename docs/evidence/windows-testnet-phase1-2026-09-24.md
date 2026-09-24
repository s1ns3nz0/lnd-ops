# Windows testnet Phase 1 evidence (2026-09-24)

Tested runtime revision: `c1312c94c1ba1d3b098d7582b4d872f5324aa2ae`; the Windows checkout was clean at final inspection. Host: Windows 11 Home, WSL 2 Ubuntu 24.04.5 LTS, amd64, kernel `6.18.33.2-microsoft-standard-WSL2`, single-node K3s. The revision pins the chart, scripts, image digests, and verification code used by the run. This record contains no wallet password, seed, macaroon, invoice, payment hash, payment preimage, SCB bytes, encryption passphrase, recovery key, or kubeconfig.

The authoritative Phase 1 requirements are in [Portfolio demo roadmap](../portfolio-demo-roadmap.md#phase-1-operate-a-real-testnet-node), and the copy-and-run procedure is in [Testnet runbook](../testnet-runbook.md). For this acceptance, **recent** means within one hour, a passing redeployment record must be no older than 24 hours, and **ordinary redeployment** means Helm chart reapplication in the existing cluster without uninstalling releases or deleting namespaces, PVCs, wallets, or channels. The final acceptance command verifies its private record schema and hashes, current live state, encrypted SCB equality, monitoring, and redeployment continuity before exiting successfully.

## Testnet operation

- `ops/acceptance testnet` passed at `2026-09-24T06:23:02Z`.
- LND was synchronized to Bitcoin testnet and retained node identity `03e8babd6aff358420d6d89500a1a01ac43cb1f6b67c25a9631778a6d1c3f37df2`.
- The active public channel was `4ef4d09133b47bfdab9ccc27284671aaa39c766102c6aba36eceb8c510392a99:1` with peer `02312627fdf07fbdd7e5ddb136611bdde9b00d26821d14d94891395452f67af248`.
- The public channel was active with 100,000 sat capacity, 71,518 sat local balance, and 25,012 sat remote balance at evidence collection time.
- These are LND-reported balances; channel reserve and commitment accounting explain why they need not sum to capacity.
- The node had three connected peers. The final one-hour acceptance window contained one successful outgoing payment and one settled incoming invoice.
- The independent test-only payer was a distinct LND wallet and node identity in the same Kubernetes namespace. `lnd-0` funded its direct private channel `5a574975377f169492fc0b63c7bdf5dc02f9da16deed6d78293c0a89f301dd76:0` and pushed payer-side balance at channel creation. The payer then settled an `lnd-0` invoice over that real testnet channel. This provides deterministic incoming evidence without claiming an externally routed payment or relying on a public faucet website.

## Restart and monitoring result

- `ops/testnet-reconnect-check` restarted only `pod/lnd-0-0`, then proved the replacement Pod had a different Pod UID while restoring the same node identity, active public channel point, and connected public-channel peer. The recovery check completed in 205 seconds, including the operator-controlled wallet unlock interval.
- `ops/verify-monitoring --profile testnet` passed Grafana, Prometheus 14-day retention, Alertmanager, Kubernetes and disk metrics, LND scrapes, chain signal, and recent send/receive payment samples.
- The monitoring checks used live LND and Kubernetes data. Fixture-only or empty panels were not accepted as evidence.

## Encrypted SCB result

Windows Home did not expose Device Encryption because Secure Boot remained disabled. The documented temporary encrypted-file workflow was used pending the Phase 5 host-hardening work.

- `ops/backup-scb-encrypted testnet lnd-0` streamed the current SCB into a GPG AES-256 symmetric ciphertext using SHA-512 for S2K derivation and loopback pinentry, without writing a plaintext host copy.
- Immediate decrypt-and-hash verification passed.
- SCB format: `gpg-symmetric-v1`.
- Live and verified plaintext SHA-256: `a876884fffa3b2e18f911694ad91732fdee67f5b96a0e2bd3b258f8a3aff8a17`.
- Stored ciphertext SHA-256: `1efc15b6474d9e764ac18fe917e9cab9f341743770c3c94a996c84541ee2892c`.
- The passphrase is retained by the operator outside the repository and is required to use this recovery copy.
- This phase proves current-copy integrity and decryptability at creation time. It does not claim channel recovery; the isolated seed-plus-SCB recovery exercise remains a Phase 5 gate.

## Wallet-preserving redeployment

`ops/redeploy-check` passed from `2026-09-24T06:21:48Z` through `06:22:10Z`. The LND Helm revision advanced from 3 to 4 and the monitoring revision advanced from 3 to 4.

The verifier proved equality before and after chart reapplication for:

- LND node identity;
- both public and private channel points;
- LND PVC UID `db77330c-2b32-4a31-bc7c-b91be650c0e4`;
- Prometheus PVC UID `e7cddd0e-5705-439c-8434-eec9537c7e7d`;
- current SCB plaintext and encrypted-copy hashes;
- Kubernetes cluster identity hash;
- one exact historical Prometheus series, timestamp, and value.

The private redeployment record is `testnet-redeploy-20260924T062148.731683Z.json`, SHA-256 `03c2aca0ee956339e68e939deaf00873794b661533d59831943caaaaf9cf296f`. The final private acceptance record is `testnet-acceptance-20260924T062302.127252Z.json`, SHA-256 `0f47b43740d89fc4af3b7df2f80d6a6e8aad3fe3041c80fd476ca3e06e2c22e5`. Both remain operator-owned mode `0600` under `${XDG_STATE_HOME:-$HOME/.local/state}/lnd-ops/evidence/` and are excluded from Git.

The published node key, peer key, channel points, PVC UIDs, and SHA-256 values are intentional non-secret correlation identifiers. The raw evidence records remain private; their recorded digests allow the operator to demonstrate later that the inspected files are unchanged.

## Result and limitations

Windows Phase 1 passed: the persistent node used a real external testnet peer and public channel, completed payments in both directions, exposed live operations data, restored its channel peer after a Pod restart, maintained a current encrypted SCB, and preserved wallet, channel, storage, and monitoring history across ordinary redeployment.

At the time of this Windows Phase 1 record, the Mac arm64 testnet proof remained a Phase 8 requirement; it later passed in [the cross-platform Phase 8 evidence](phase8-cross-platform-2026-09-24.md). Windows Secure Boot and Device Encryption remain deferred host-hardening work, while the isolated seed-plus-SCB recovery exercise later passed in Phase 5. The test-only payer PVC is retained for future incoming-payment evidence, but its StatefulSet is disabled after the final repeat deployment because the canonical persistent testnet profile runs one primary node.
