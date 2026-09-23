# K3s guest root filesystem low

1. Confirm guest filesystem usage with `df -h /` inside the Mac Lima VM or Windows WSL 2 Ubuntu distribution. Compare the alert's `instance` label with the active K3s node.
2. Check whether image layers, container logs, or local-path volumes are responsible. Check Pod events and PVC usage before removing any data.
3. Never delete an LND, Bitcoin Core, or Prometheus PVC to clear space. Increase guest storage or remove confirmed disposable files using the host-specific procedure, then verify free space and alert resolution.
