# LND PVC storage low

## Trigger

`LndOpsPVCStorageLow` fires when an LND PVC has less than 10% free space for five minutes.

## Diagnose

1. Identify the namespace and PVC from the alert labels.
2. Compare `kubelet_volume_stats_available_bytes` and `kubelet_volume_stats_capacity_bytes` with guest filesystem availability.
3. Inspect the owning StatefulSet, Pod events, and PVC status. Do not inspect wallet files or macaroons.
4. Determine whether growth comes from LND chain data, logs, or an unrelated volume.

## Recover

Expand storage through a reviewed platform change when the storage class supports it. Do not delete the PVC, wallet database, channel database, or SCB. Run `ops/verify <profile>` and `ops/verify-monitoring --profile <profile>` afterward.
