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

## Security design

- Scope the first threat model to accidental Kubernetes misconfiguration or a compromised Pod reaching LND credentials, wallet data, or the management API.
- Do not add a separate firewall product. Use Kubernetes NetworkPolicy for Pod traffic; document Windows host firewall configuration as a host prerequisite.
- Apply default-deny ingress and egress to the LND namespace, then allow only required DNS, peer, Neutrino, and monitoring traffic. Test the real connection paths before considering the policy complete.
- Use dedicated LND and lndmon ServiceAccounts without Kubernetes API permissions or automatically mounted tokens. Give lndmon a separate read-only macaroon. Keep the admin macaroon on the LND persistent volume and the wallet seed offline.
- Target the `restricted` Kubernetes Pod Security Admission profile for the LND namespace. Assess monitoring components separately and document any namespace-level exception. Copy SCBs from the WSL 2 host with a systemd timer, so the backup process does not require a Pod with a Windows drive hostPath mount.
- Install Kyverno for project namespaces only. Check image digest and resource-limit policies in audit mode, correct violations, then enforce the verified rules. Exclude K3s system and Falco namespaces from those project policies.
- Run Falco as a node-level sensor in a separate security namespace, using modern eBPF if the WSL 2 kernel supports it. Confirm real kernel events are collected. Send a test event through the local dashboard and Alertmanager; do not count an installed but inactive sensor as a success.
- Enable K3s Secret encryption at rest at cluster installation. Keep the administrator kubeconfig inside Windows WSL 2; do not copy it to macOS or the repository.
- Defer the Windows device-encryption and recovery-key check until the Windows setup phase; complete it before funding the testnet wallet.
- Defer Vault and cert-manager. The first Vault integration will hold service credentials such as lndmon's read-only macaroon, not the wallet seed or admin macaroon. Use cert-manager only if certificate issuance or renewal becomes necessary.

### Security acceptance criteria

1. A Pod with an unpinned image or missing resource limits is rejected by an enforced Kyverno policy; a Pod violating the LND namespace's Pod Security Admission level is rejected.
2. A test Pod outside the explicit NetworkPolicy allowlist cannot reach LND's management API. The runbook must state the test Pod, port, and expected result.
3. Kubernetes authorization checks show that LND and lndmon ServiceAccounts cannot read API resources, and neither Pod mounts a ServiceAccount token.
4. A Falco test event reaches the local dashboard and Alertmanager. If the WSL 2 kernel cannot run the sensor, record this criterion as unmet rather than silently substituting an inactive installation.

## Later stages

- Add Lightning Terminal (`litd`) connected to the separately deployed LND.
- Add Vault for in-cluster service credential management.
- Evaluate inbound peer connectivity after the outbound workflow works.
- Evaluate an off-PC automated backup target and disaster recovery.

## Constraints

- The Neutrino and Bitcoin Core configurations are separate environments. Do not treat a backend change on a funded LND wallet as a configuration-only switch.
- Do not commit wallet seeds, macaroons, wallet passwords, or channel backups.
- Keep WSL 2 Linux workload data on the Ubuntu filesystem. Use the Windows folder only for the SCB copy.
