# LND operator plan

## Goal

Build a reproducible Lightning Labs platform engineering portfolio project. Develop and validate on macOS; demonstrate on a Windows 11 Home PC with 64 GB RAM and 1 TB storage.

## Agreed MVP

- Run a single-node K3s cluster inside Ubuntu on WSL 2.
- Deploy LND on Bitcoin testnet3 with a Neutrino chain backend. Use a persistent volume for LND data. Unlock the wallet manually after startup.
- Use Bitcoin Core with regtest for local integration and recovery exercises on macOS. Validate Kubernetes resources with a local kind cluster.
- Add lndmon, Prometheus, Grafana, and Alertmanager. Manage LND and its operating policy in a project Helm chart; install general monitoring components from maintained charts.
- Reach Grafana and LND management interfaces through local `kubectl port-forward` sessions.
- Connect to peers outbound first. Open a testnet channel and make a payment.
- Automatically copy LND's Static Channel Backup (SCB) to `C:\lnd-ops-backups` on the same Windows PC. Keep the wallet seed offline. Document manual transfer of the SCB to the development Mac. The local copy alone does not cover loss of the PC.
- Clone this GitHub repository inside WSL 2 and run documented Helm deployment commands there.

## Demonstration acceptance criteria

1. Install the testnet LND stack from Helm on WSL 2 K3s.
2. Open a channel, make a payment, and observe state changes in Grafana.
3. Stop and restart LND, see an alert, unlock the wallet manually, and verify the SCB copy and backup-age signal.

This records product decisions, not installation instructions. Version pins, chart sources, commands, alert thresholds, and evidence collection belong in the implementation runbooks.

## Later stages

- Add Lightning Terminal (`litd`) connected to the separately deployed LND.
- Add Vault for in-cluster secret management.
- Evaluate inbound peer connectivity after the outbound workflow works.
- Evaluate an off-PC automated backup target and disaster recovery.

## Constraints

- The Neutrino and Bitcoin Core configurations are separate environments. Do not treat a backend change on a funded LND wallet as a configuration-only switch.
- Do not commit wallet seeds, macaroons, wallet passwords, or channel backups.
- Keep WSL 2 Linux workload data on the Ubuntu filesystem. Use the Windows folder only for the SCB copy.
