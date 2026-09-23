import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const repo = resolve(import.meta.dirname, '..');
const script = join(repo, 'ops/check-host-encryption');

function executable(path, body) {
  writeFileSync(path, body, { mode: 0o755 });
}

function runWith(bin, args = ['--confirm-recovery-key-recorded'], extraEnv = {}) {
  return spawnSync(script, args, {
    cwd: repo,
    env: { ...process.env, PATH: `${bin}:/usr/bin:/bin`, ...extraEnv },
    encoding: 'utf8',
  });
}

test('requires explicit recovery-key confirmation', () => {
  const result = spawnSync(script, [], { cwd: repo, encoding: 'utf8' });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /Record the host recovery key offline/);
});

test('check-only verifies encryption but leaves recovery-key gate pending', () => {
  const bin = mkdtempSync(join(tmpdir(), 'lnd-ops-filevault-'));
  executable(join(bin, 'uname'), '#!/bin/sh\necho Darwin\n');
  executable(join(bin, 'fdesetup'), '#!/bin/sh\necho true\n');
  const result = runWith(bin, ['--check-only']);
  assert.equal(result.status, 10);
  assert.match(result.stdout, /FileVault protects/);
  assert.match(result.stderr, /record the host recovery key offline/);
  assert.doesNotMatch(result.stdout, /gate passed/);
});

test('passes an active FileVault host', () => {
  const bin = mkdtempSync(join(tmpdir(), 'lnd-ops-filevault-'));
  executable(join(bin, 'uname'), '#!/bin/sh\necho Darwin\n');
  executable(join(bin, 'fdesetup'), '#!/bin/sh\n[ "$1" = isactive ] && echo true\n');
  const result = runWith(bin);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /FileVault protects/);
  assert.match(result.stdout, /pre-funding gate passed/);
});

test('rejects an inactive FileVault host', () => {
  const bin = mkdtempSync(join(tmpdir(), 'lnd-ops-filevault-'));
  executable(join(bin, 'uname'), '#!/bin/sh\necho Darwin\n');
  executable(join(bin, 'fdesetup'), '#!/bin/sh\necho false\n');
  const result = runWith(bin);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /FileVault is not active/);
});

test('uses the Windows protection check from WSL', () => {
  const bin = mkdtempSync(join(tmpdir(), 'lnd-ops-bitlocker-'));
  const osrelease = join(bin, 'osrelease');
  writeFileSync(osrelease, '6.6.0-microsoft-standard-WSL2\n');
  executable(join(bin, 'uname'), '#!/bin/sh\necho Linux\n');
  executable(join(bin, 'wslpath'), '#!/bin/sh\necho C:\\\\repo\\\\ops\\\\windows-encryption-status.ps1\n');
  executable(join(bin, 'powershell.exe'), '#!/bin/sh\nprintf "%s\\n" "$@"\necho "OK: Windows volume D: containing the WSL 2 data is protected"\n');
  const result = runWith(bin, undefined, {
    LND_OPS_OSRELEASE_FILE: osrelease,
    WSL_DISTRO_NAME: 'Ubuntu',
  });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /windows-encryption-status\.ps1/);
  assert.match(result.stdout, /-DistroName\nUbuntu/);
  assert.match(result.stdout, /pre-funding gate passed/);
});

test('discovers the WSL distribution name when an SSH session omits it', () => {
  const bin = mkdtempSync(join(tmpdir(), 'lnd-ops-bitlocker-'));
  const osrelease = join(bin, 'osrelease');
  writeFileSync(osrelease, '6.6.0-microsoft-standard-WSL2\n');
  executable(join(bin, 'uname'), '#!/bin/sh\necho Linux\n');
  executable(join(bin, 'wslpath'), '#!/bin/sh\nif [ "$2" = / ]; then printf "\\\\wsl.localhost\\Ubuntu-24.04\\\\\n"; else echo C:\\\\repo\\\\ops\\\\windows-encryption-status.ps1; fi\n');
  executable(join(bin, 'powershell.exe'), '#!/bin/sh\nprintf "%s\\n" "$@"\n');
  const result = runWith(bin, undefined, {
    LND_OPS_OSRELEASE_FILE: osrelease,
    WSL_DISTRO_NAME: '',
  });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /-DistroName\nUbuntu-24\.04/);
});

test('Windows check discovers the WSL 2 backing volume instead of assuming C:', () => {
  const source = readFileSync(join(repo, 'ops/windows-host-state.ps1'), 'utf8');
  assert.match(source, /DistributionName -eq \$DistroName/);
  assert.match(source, /Version -ne 2/);
  assert.match(source, /Join-Path \$basePath 'ext4\.vhdx'/);
  assert.match(source, /manage-bde\.exe -status \$drive/);
  assert.doesNotMatch(source, /manage-bde\.exe -status C:/);
});
