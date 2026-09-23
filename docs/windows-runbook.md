# Windows 11 Home test runbook

This is the amd64 acceptance path for the MVP. It blocks inbound Kubernetes API traffic at the Windows firewall while allowing Pods inside WSL to reach the API, stores the WSL virtual disk on its actual Windows backing volume, and writes SCBs outside that virtual disk on the same encrypted volume. A same-PC backup does not cover loss of the PC.

## 1. Enable WSL 2 and systemd

Download or clone the repository to any temporary Windows folder first. From an elevated PowerShell window in that checkout:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\ops\windows-enable-wsl.ps1
```

Exit `10` means Windows requested the initial WSL installation or restart. Restart if requested, open Ubuntu once to complete its first-run user creation, close it, and rerun the PowerShell command. The script sets WSL 2 and writes `/etc/wsl.conf` with systemd enabled. Microsoft documents `wsl --install` and the systemd setting in its [WSL installation](https://learn.microsoft.com/windows/wsl/install) and [advanced settings](https://learn.microsoft.com/windows/wsl/wsl-config) guides.

## 2. Install operator prerequisites

The acceptance target is the current Ubuntu distribution named `Ubuntu`, amd64, with systemd. Give WSL at least 8 CPU cores, 16 GiB RAM, and 100 GiB free disk for the acceptance run. Internet access to GitHub and the OCI registries listed in `ops/images.lock.json` is required.

Clone the repository again into the WSL Linux filesystem, such as `~/src/lnd-ops`, rather than running the deployment from `/mnt/c`. The project installs Docker Engine, Buildx, Git, curl, CA certificates, Python 3, `skopeo`, and checksum-pinned Helm and kubectl builds:

```sh
git clone https://github.com/s1ns3nz0/lnd-ops.git ~/src/lnd-ops
cd ~/src/lnd-ops
ops/windows-install-prereqs
```

The script may exit `10` after adding the Linux user to the Docker group. Close Ubuntu, run `wsl --shutdown` in PowerShell, reopen Ubuntu, and check the exact requirements:

```sh
cd ~/src/lnd-ops
ops/doctor
```

The command fails with a list of missing requirements. It also rejects Windows versions other than Windows 11, WSL 1, non-amd64 WSL, and WSL without systemd.

## 3. Run the automated infrastructure acceptance test

```sh
ops/windows-smoke 2>&1 | tee windows-smoke.log
```

The script verifies linux/amd64 and linux/arm64 support for the locked OCI indexes, installs the pinned K3s release after checking the installer hash, requires the Windows inbound TCP 6443 block rule, deploys regtest and testnet, and verifies Prometheus, Grafana, Alertmanager, and the policy/runtime-security infrastructure. It downloads from the configured public registries and leaves a K3s cluster plus wallet-free PVCs. It is safe to rerun after a partial failure because Helm uses upgrade/install semantics. On a fresh host, wallet checks are reported as `PENDING`; they are manual gates and do not fail the infrastructure test. Any other nonzero exit is a failure.

Expected final line:

```text
OK: Windows WSL 2 infrastructure smoke test passed
```

Do not commit `windows-smoke.log`; it is ignored. Confirm from Windows PowerShell that port 6443 is not listening on a LAN address:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 6443 -ErrorAction SilentlyContinue |
  Select-Object LocalAddress,LocalPort,State
```

No output is acceptable. A loopback-forwarded row with `127.0.0.1` or `::1` is also acceptable. Any `0.0.0.0`, `::`, LAN, or Wi-Fi address is a failure; stop K3s with `wsl -d Ubuntu -- sudo systemctl stop k3s` before investigating.

## 4. Host encryption gate

Before funding a testnet wallet, run this inside Ubuntu:

```sh
ops/check-host-encryption --check-only
```

The check discovers the Windows volume that actually contains this distribution's `ext4.vhdx`; it does not assume `C:`. Exit `10` means volume protection passed and only the independent recovery-key custody confirmation remains. After storing and validating the recovery key outside this PC:

```sh
ops/check-host-encryption --confirm-recovery-key-recorded
```

## 5. Wallet and repeat-deployment tests

Create the LND wallets running inside the Windows WSL Kubernetes cluster interactively and keep their seeds out of the repository. Regtest requires the two wallets `lnd-0` and `lnd-1`; testnet uses its own later wallet. Follow the [regtest runbook](regtest-runbook.md), including its channel and bidirectional payment steps, then use:

```sh
ops/exercise-regtest
ops/backup-scb regtest lnd-0
ops/backup-scb regtest lnd-1
ops/redeploy-check regtest
```

On Windows, the backup scripts use `<WSL-backing-drive>:\lnd-ops-backups`, apply an ACL for the current Windows user and SYSTEM, and verify the copied SCB hash. Existing wallet PVCs are reused during ordinary redeployment.

## 6. Disposable clean-start proof

Only run the destructive commands in the [clean-start runbook](clean-start-runbook.md) after `ops/reset-disposable regtest --confirm-unfunded` and `ops/reset-disposable testnet --confirm-unfunded` both positively inspect the data and succeed. The K3s uninstall removes its datastore and local PVC data. Once any wallet exists, preserve the PVC and use `ops/redeploy-check` instead.

Copy [the evidence template](evidence/windows-template.md) to `docs/evidence/windows-YYYY-MM-DD.md` and commit the completed copy. It must contain:

- `winver`, `wsl --version`, `wsl --list --verbose`, architecture, and K3s version;
- exit codes for `windows-smoke`, the encryption gate, `exercise-regtest`, both SCB copies, and `redeploy-check`;
- regtest PVC UIDs before and after redeployment, showing exact equality;
- the final success lines and hashes printed by the scripts, with usernames and host paths redacted.

Never include seeds, passwords, macaroons, recovery keys, raw SCBs, kubeconfig contents, or the smoke log. Infrastructure acceptance is complete at the final `windows-smoke` success line. The Windows functional MVP exit check is complete only after encryption, wallets, the regtest channel/payments, both SCB copies, and wallet-preserving redeployment also pass on the real PC.

## Optional: Mac read-only operator access to WSL logs

To let the operator Mac read WSL logs without enabling SMB, create a dedicated Ed25519 key on the Mac and copy only its `.pub` line. Open Ubuntu using **Run as administrator**, pull the latest repository, and run:

```sh
git pull
ops/windows-enable-log-access \
  --public-key 'ssh-ed25519 AAAA... lnd-ops-mac-access' \
  --allowed-client-ip 172.30.1.14 \
  --linux-user miata
```

The Ubuntu script installs OpenSSH Server, disables SSH password and root login, installs the supplied public key, uses Windows `netsh.exe` to map TCP 2222 to WSL TCP 22, and permits that Windows port only from the supplied Mac IPv4 address on private networks. The WSL NAT address can change after `wsl --shutdown`; rerun the script to refresh the mapping when that happens.

The Mac can then read the project directly:

```sh
ssh -i ~/.ssh/lnd_ops_wsl -p 2222 miata@172.30.1.70 \
  'cd /home/miata/src/lnd-ops && tail -n 100 windows-smoke.log'
```
