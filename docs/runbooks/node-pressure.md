# K3s node pressure

## Trigger

`LndOpsNodePressure` fires when Kubernetes reports DiskPressure, MemoryPressure, or PIDPressure for five minutes.

## Diagnose

1. Read the `node` and `condition` labels from the alert.
2. Inspect node conditions, allocatable resources, Pod requests, Pod usage, and recent events.
3. Correlate DiskPressure with guest filesystem and PVC panels; correlate MemoryPressure with container working sets and limits.
4. Keep LND PVCs and wallet-bearing workloads protected during cleanup decisions.

## Recover

Remove only reviewed disposable data or increase host resources. Never delete funded PVCs, SCBs, wallets, or weaken resource/security controls. Verify the node becomes Ready and rerun monitoring checks.
