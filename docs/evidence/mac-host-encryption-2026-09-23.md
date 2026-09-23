# Mac host-encryption check (2026-09-23)

Host: macOS arm64.

`ops/check-host-encryption --check-only` verified that FileVault is active on the Mac host and that the default Lima data directory is under its protected user home. The command exited `10` because the operator has not yet confirmed that the recovery key is recorded independently of this host. This is a pending pre-funding gate and does not authorize testnet funding.

The automated tests also exercised active and inactive FileVault results, the pending check-only result, and a mocked WSL-to-Windows protection-check invocation. The actual Windows 11 Home encryption state remains untested on the target PC.
