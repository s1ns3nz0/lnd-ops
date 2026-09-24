# Phase 8 cross-platform acceptance

Phase 8 proves that the documented command surface works on Mac arm64 and
Windows WSL 2 amd64, that each host's independent testnet wallet passes the
functional and security gates, and that the same Git revision passes the
platform-independent GitHub CI gates.

## Mac clean start

Run the isolated wallet-free proof without changing the persistent Mac cluster:

```sh
ops/exercise-clean-start --cleanup
```

The command creates a separate `lnd-ops-phase8-clean` Lima VM, uses a separate
kubeconfig and API port, runs the wallet-free stack twice, records owner-only
evidence, and removes only that isolated VM after success.

## Host runtime proof

On each persistent host, complete the host's independent testnet wallet,
channel, bidirectional payment, encrypted SCB, monitoring, redeployment, and
Phase 4 security workflow. Then run:

```sh
ops/phase8-host-acceptance
```

Exit `10` identifies an operator or freshness gate. The command does not create
wallets, initiate payments, open channels, or read credentials. A pass writes a
mode `0600` `phase8-host-*.json` record.

Copy the Windows host record to an owner-only temporary location on the Mac.
The record contains hashes, host labels, Git revisions, and evidence filenames;
it contains no wallet secret or payment material. From the same clean Git
revision on Mac, run:

```sh
chmod 600 /path/to/windows-phase8-host.json
ops/phase8-acceptance /path/to/windows-phase8-host.json
```

The final command requires Mac and Windows host records from the current Git
revision, no older than 24 hours, and successful `Harness check` and
`Verify operator slice` GitHub workflows for that exact revision.
