# Windows MVP evidence — YYYY-MM-DD

## Host

- Windows version (`winver`):
- WSL version (`wsl --version`):
- Distribution and WSL generation (`wsl --list --verbose`):
- Architecture:
- K3s version:
- Backing drive encryption check: pass / fail
- Recovery-key custody confirmation: pass / fail

## Infrastructure acceptance

- `ops/windows-smoke` exit code:
- Final success line:
- Windows port 6443 listener result: none / loopback only
- Regtest PVC UIDs:
- Testnet PVC UID:
- Monitoring infrastructure verification:

## Functional acceptance

- `ops/exercise-regtest` exit code:
- Channel and bidirectional payment result:
- `lnd-0` SCB copy/status result and SHA-256:
- `lnd-1` SCB copy/status result and SHA-256:
- `ops/redeploy-check regtest` exit code and evidence path:
- Regtest PVC UIDs after redeployment:
- Node identities, channels, SCBs, and Prometheus history preserved: yes / no

## Clean-start acceptance

- Wallet-free confirmation commands and exit codes:
- K3s uninstall result:
- Project image-cache reset result:
- Second `ops/windows-smoke` exit code:
- Recreated PVC UIDs:

## Redaction check

Confirmed absent: seeds, passwords, macaroons, recovery keys, raw SCBs, kubeconfig contents, Windows username, and absolute host paths.
