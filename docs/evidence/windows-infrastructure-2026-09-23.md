# Windows infrastructure acceptance — 2026-09-23

The target was Windows 11 Home, Ubuntu 24.04 WSL 2 on amd64, and K3s `v1.36.4+k3s1`. The repository was cloned into the WSL ext4 filesystem and the pinned project scripts were used from a previously empty K3s installation.

The first deployment exposed a real portability defect: binding the K3s API to `127.0.0.1` let host kubectl work but prevented Pods from reaching the Kubernetes Service endpoint. CoreDNS, metrics-server, and local-path-provisioner could not reach `10.43.0.1:443`; all workload PVCs remained Pending. The corrected configuration lets K3s listen on WSL interfaces and blocks inbound TCP 6443 at Windows Firewall instead. After the K3s restart, all three original PVC claims bound without deletion and the original Helm release upgraded successfully.

A second WSL-specific defect appeared in monitoring: node-exporter's default `HostToContainer` propagation rejected the WSL root mount because `/` is not shared. Setting only the read-only root mount propagation to `None` preserved the host metrics mount and allowed the DaemonSet to start. The failed Helm revision was upgraded in place.

Final secret-free observations:

- Mac external check: Windows TCP 6443 timed out; restricted operator SSH TCP 2222 was reachable.
- K3s Node: Ready.
- kube-system: CoreDNS, local-path-provisioner, and metrics-server Ready.
- regtest: Bitcoin and both LND Pods Ready; PVC UIDs `pvc-9c819cee-dcb1-4e84-83d6-89a99e1e9fef`, `pvc-c544745b-dad5-4ba1-8221-a1d926e91f93`, and `pvc-b92f7260-4fbc-41c2-8fc1-83375fed53d8` Bound.
- testnet: LND Pod Ready; PVC UID `pvc-db77330c-2b32-4a31-bc7c-b91be650c0e4` Bound.
- monitoring: Grafana, Prometheus, Alertmanager, operator, kube-state-metrics, and node-exporter Ready; Prometheus PVC UID `pvc-e7cddd0e-5705-439c-8434-eec9537c7e7d` Bound.
- `ops/verify-monitoring --infrastructure-only` passed and the acceptance path printed `OK: Windows WSL 2 infrastructure smoke test passed`.

The fresh Windows wallets remain intentionally absent. Regtest and testnet verification stopped at their documented manual wallet gates, so wallet, channel, payment, SCB, wallet-preserving redeployment, and live LND monitoring acceptance on Windows remain pending.
