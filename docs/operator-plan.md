# LND operator plan

## Goal

Build a reproducible Lightning Labs platform engineering portfolio project. Run the same stack on an arm64 Mac and a Windows 11 Home PC with 64 GB RAM and 1 TB storage. Each machine has its own Linux K3s instance and separate testnet wallet.

## Agreed target architecture

- Run single-node K3s inside a Lima Linux VM on macOS and inside Ubuntu on WSL 2 on Windows.
- Deploy LND on Bitcoin testnet3 with a Neutrino chain backend. Use a persistent volume for LND data. Unlock the wallet manually after startup.
- Offer both testnet3/Neutrino and regtest/Bitcoin Core profiles on each machine. Use regtest for recovery exercises and testnet for the full node demonstration.
- Add lndmon, Prometheus, Grafana, and Alertmanager. Manage LND and its operating policy in a project Helm chart; install general monitoring components from maintained charts.
- Reach Grafana and LND management interfaces through local `kubectl port-forward` sessions.
- Connect to peers outbound first. Open a testnet channel and make a payment.
- Automatically copy each node's Static Channel Backup (SCB) outside its K3s data volume: `C:\lnd-ops-backups` on Windows and a dedicated macOS host folder on Mac. Keep each wallet seed offline. Same-machine copies do not cover loss of that machine.
- Clone this GitHub repository on either machine and run the same profile-specific deployment commands. Keep wallets and persistent data separate across machines and networks.

## End-to-end portfolio demonstration criteria

1. Install the testnet LND stack from Helm on both Mac Lima K3s and Windows WSL 2 K3s.
2. Open a channel, make a payment, and observe state changes in Grafana.
3. Stop and restart LND, see an alert, unlock the wallet manually, and verify the SCB copy. Backup-age alerting is a later observability extension.

This records product decisions, not installation instructions. Version pins, chart sources, commands, alert thresholds, and evidence collection belong in the implementation runbooks.

The [implementation roadmap](implementation-roadmap.md) defines the smaller core MVP and the order of later portfolio features.

## Security design

- Scope the first threat model to accidental Kubernetes misconfiguration or a compromised Pod reaching LND credentials, wallet data, or the management API.
- Do not add a separate firewall product. Use Kubernetes NetworkPolicy for Pod traffic; document each host's firewall configuration as a prerequisite.
- Apply default-deny ingress and egress to the LND namespace, then allow only required DNS, peer, Neutrino, and monitoring traffic. Test the real connection paths before considering the policy complete.
- Use dedicated LND and lndmon ServiceAccounts without Kubernetes API permissions or automatically mounted tokens. Give lndmon a separate read-only macaroon. Keep the admin macaroon on the LND persistent volume and the wallet seed offline.
- Target the `restricted` Kubernetes Pod Security Admission profile for the LND namespace. Assess monitoring components separately and document any namespace-level exception. Copy SCBs with a Linux guest or host job that does not require the LND Pod to mount host filesystems.
- Install Kyverno for project namespaces only. Check image digest and resource-limit policies in audit mode, correct violations, then enforce the verified rules. Exclude K3s system and Falco namespaces from those project policies.
- Run Falco as a node-level sensor in a separate security namespace, using modern eBPF if each guest kernel supports it. Confirm real kernel events are collected on both machines. Send a test event through the local dashboard and Alertmanager; do not count an installed but inactive sensor as a success.
- Enable K3s Secret encryption at rest at cluster installation. Keep each administrator kubeconfig on its own machine and out of the repository.
- Defer the Windows device-encryption and recovery-key check until the Windows setup phase; complete it before funding the testnet wallet.
- Defer Vault and cert-manager. The first Vault integration will hold service credentials such as lndmon's read-only macaroon, not the wallet seed or admin macaroon. Use cert-manager only if certificate issuance or renewal becomes necessary.

### Security acceptance criteria

1. A Pod with an unpinned image or missing resource limits is rejected by an enforced Kyverno policy; a Pod violating the LND namespace's Pod Security Admission level is rejected.
2. A test Pod outside the explicit NetworkPolicy allowlist cannot reach LND's management API. The runbook must state the test Pod, port, and expected result.
3. Kubernetes authorization checks show that LND and lndmon ServiceAccounts cannot read API resources, and neither Pod mounts a ServiceAccount token.
4. A Falco test event reaches the local dashboard and Alertmanager on both machines. If either guest kernel cannot run the sensor, record this criterion as unmet rather than silently substituting an inactive installation.

## Later stages

- Add Lightning Terminal (`litd`) connected to the separately deployed LND.
- Add Vault for in-cluster service credential management.
- Evaluate inbound peer connectivity after the outbound workflow works.
- Evaluate an off-PC automated backup target and disaster recovery.

## Constraints

- The Neutrino and Bitcoin Core configurations are separate environments. Do not treat a backend change on a funded LND wallet as a configuration-only switch.
- Do not commit wallet seeds, macaroons, wallet passwords, or channel backups.
- Keep Linux workload data on each guest's Linux filesystem. Use host folders only for SCB copies.
