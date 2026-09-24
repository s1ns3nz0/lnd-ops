# LND TLS certificate expiring

1. Confirm `lnd_ops_tls_certificate_expiry_timestamp_seconds` is present and compare it with the current time. This metric exposes only the expiry timestamp.
2. Inspect the live certificate subject and dates locally without copying its private key, macaroons, wallet password, seed, or SCB.
3. Schedule LND's documented TLS certificate rotation while preserving the wallet PVC. Rotation may restart LND and require the operator to unlock the wallet manually.
4. Reconnect dependent local clients using the new certificate. Do not introduce cert-manager solely for LND's self-managed certificate unless a separately reviewed issuer and rotation design exists.
5. Verify the new expiry metric, LND and lndmon scrapes, active channels, encrypted SCB status, and `ops/phase3-acceptance`.

