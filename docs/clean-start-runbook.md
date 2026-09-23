# Clean-start and repeat-deployment proof

Use this procedure on each target host. Prove infrastructure recreation with wallet-free disposable resources. After creating a wallet, keep its PVC and reuse the wallet for functional and ordinary redeployment checks. Record the host, architecture, cleanup command, fresh-run command, PVC UIDs, exit codes, and secret-free observations. An exit code `10` at a wallet or funding gate is a pending stage, not a pass.

## Data boundary

`ops/reset-disposable regtest|testnet --confirm-unfunded` refuses to delete a namespace unless it can positively verify that every LND wallet database in that profile is absent. It is only for wallet-free deployments. The regtest recovery reset has its own verified procedure in [the regtest runbook](regtest-runbook.md). Never use a VM deletion, K3s uninstall, or namespace deletion as an ordinary redeploy of a funded node. Preserve the offline seed and host SCB outside the K3s volume; do not include either in evidence.

For a clean cluster proof, use a dedicated disposable project cluster with no funded wallet or unrelated workloads. Confirm `kubectl get namespaces` and `kubectl get pvc -A` before removing it. If a wallet or unrelated PVC exists, stop the destructive proof and use a separate disposable environment. A funded node instead uses `ops/redeploy-check`, which reapplies charts and compares identity, channel, PVC, SCB, and monitoring history.

After the scripts recreate and verify a wallet-free stack, the operator may create the wallets in that same cluster. From that point onward, keep those wallets and PVCs. “Redeploy” then means chart reapplication and resulting Pod recreation only; do not uninstall the release, delete its namespace, recreate K3s, or repeat the destructive clean-start procedure against that wallet-bearing environment.

## Mac arm64: empty project VM

On a disposable Mac project VM, remove wallet-free project namespaces with the guarded scripts, then remove monitoring and the Lima VM. `ops/bootstrap` installs a pinned Lima CLI under `${XDG_DATA_HOME:-$HOME/.local/share}/lnd-ops/tools/` if `limactl` is not already available. Use that CLI path if needed. The full VM removal also removes the K3s image store, PVCs, and cluster; it does not clear Docker's build cache. Record whether the project collector image tag remains in the host Docker image store, and remove that tag if the test requires an empty host image cache.

```sh
export KUBECONFIG="${XDG_STATE_HOME:-$HOME/.local/state}/lnd-ops/kubeconfig"
. ops/versions.env
export PATH="${XDG_DATA_HOME:-$HOME/.local/share}/lnd-ops/tools/lima-$LIMA_VERSION/bin:$PATH"
ops/reset-disposable regtest --confirm-unfunded
ops/reset-disposable testnet --confirm-unfunded
kubectl delete namespace lnd-monitoring --ignore-not-found --wait=true
kubectl get pvc -A
limactl stop lnd-ops-k3s
limactl delete --force lnd-ops-k3s
ops/reset-project-image-cache --confirm-cluster-removed
```

Check that the Lima VM is absent and run the repository entry points from the fresh state:

```sh
limactl list
ops/doctor
ops/check-images
ops/bootstrap
ops/doctor
ops/deploy regtest
ops/verify regtest
ops/deploy testnet
ops/verify testnet
ops/deploy-monitoring
ops/verify-monitoring --infrastructure-only
```

Both `ops/verify` invocations should stop at the explicit wallet gate until the operator creates wallets. Do not describe this infrastructure result as the stage 2, 3, or 4 functional exit check. The [latest Mac clean-start evidence](evidence/mac-full-clean-wallet-state-2026-09-22.md) records a VM deletion and recreation with the current wallet-state monitoring configuration; subsequent changes still need their own clean-run proof.

## Windows 11 Home: fresh WSL 2 Ubuntu

Start in a prepared WSL 2 Ubuntu distribution with systemd, Docker/Buildx, Helm, kubectl, Python 3, skopeo, network access, and operator privileges. Run the same repository scripts inside Ubuntu:

```sh
ops/doctor
ops/check-images
ops/bootstrap
export KUBECONFIG="${XDG_STATE_HOME:-$HOME/.local/state}/lnd-ops/kubeconfig"
ops/doctor
ops/deploy regtest
ops/verify regtest
ops/deploy testnet
ops/verify testnet
ops/deploy-monitoring
ops/verify-monitoring --infrastructure-only
```

The Windows clean-cluster repeat must use a disposable WSL project installation with no funded or unrelated PVCs. After checking namespaces and PVCs, use the guarded reset scripts and remove monitoring. The K3s installer-provided uninstall script then removes the local datastore, local-storage PV data, and K3s configuration. [K3s documents that data loss behavior](https://docs.k3s.io/installation/uninstall).

```sh
ops/reset-disposable regtest --confirm-unfunded
ops/reset-disposable testnet --confirm-unfunded
kubectl delete namespace lnd-monitoring --ignore-not-found --wait=true
kubectl get namespaces
kubectl get pvc -A
sudo /usr/local/bin/k3s-uninstall.sh
ops/reset-project-image-cache --confirm-cluster-removed
ops/bootstrap
ops/deploy regtest
ops/verify regtest
ops/deploy testnet
ops/verify testnet
ops/deploy-monitoring
ops/verify-monitoring --infrastructure-only
```

Run the uninstall command only when the preceding listing shows no unrelated workloads or PVCs. This Windows procedure is specified but has not yet been run on the target PC.

## Functional gates after infrastructure

1. Regtest: create two separate wallets interactively once per host, record their seeds offline, run `ops/exercise-regtest`, copy both SCBs, prove ordinary chart reapplication preserves the wallets, and complete the isolated seed and SCB recovery. Recreating the wallets after a successful recovery is not required.
2. Host encryption: run `ops/check-host-encryption --check-only`. Exit `10` means volume protection passed but recovery-key custody is still pending. Store the recovery key somewhere usable without the encrypted host, such as a paper copy or a password manager accessible from another device; never put it in the repository, WSL filesystem, shell history, screenshots, or on that host alone. Confirm that it belongs to the checked host volume, then run `ops/check-host-encryption --confirm-recovery-key-recorded`. The script checks active protection and the wallet data location without reading or storing the key. Complete this gate separately on each host before testnet funding. FileVault or Windows protection may later be suspended, so rerun the check before adding funds after a host configuration change.
3. Testnet: create an independent wallet on each host, fund it manually, sync, choose a peer, open a channel, make a payment, copy the SCB to that host, and run `ops/redeploy-check`. Keep the funded PVC while proving ordinary repeat deployment. Preserve the generated JSON evidence path printed by the command; it contains public node/channel identifiers, storage UIDs, hashes, and comparison results but no wallet secret or raw monitoring labels.
4. Monitoring: enable LND monitoring after creating read-only macaroons, make fresh outgoing and incoming payments, run `ops/verify-monitoring --profile regtest|testnet`, inspect the four Grafana views, and inject a regtest fault that reaches Alertmanager. A synthetic metrics fixture alone does not prove live LND signaling.
5. Repeat the wallet-free clean-start proof and the wallet-preserving functional/redeployment proof separately on Mac arm64 and Windows amd64. Mark any missing host, payment, channel, recovery, or live monitoring result pending.
