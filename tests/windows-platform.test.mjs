import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { spawnSync } from 'node:child_process';

const repo = path.resolve(import.meta.dirname, '..');

test('windows-drive uses the encrypted WSL backing volume reported by PowerShell', async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'lnd-ops-windows-'));
  const bin = path.join(root, 'bin');
  const mounts = path.join(root, 'mnt');
  await mkdir(path.join(mounts, 'd'), { recursive: true });
  await mkdir(bin);
  await writeFile(path.join(root, 'osrelease'), '5.15.0-microsoft-standard-WSL2\n');
  const commands = {
    uname: '#!/bin/sh\n[ "$1" = -s ] && echo Linux || echo x86_64\n',
    wslpath: '#!/bin/sh\necho C:\\\\repo\\\\ops\\\\windows-encryption-status.ps1\n',
    'powershell.exe': '#!/bin/sh\necho D:\n',
  };
  for (const [name, body] of Object.entries(commands)) {
    const target = path.join(bin, name);
    await writeFile(target, body, { mode: 0o755 });
  }
  const result = spawnSync(path.join(repo, 'ops/windows-drive'), [], {
    encoding: 'utf8',
    env: {
      ...process.env,
      PATH: `${bin}:/usr/bin:/bin`,
      WSL_DISTRO_NAME: 'Ubuntu',
      LND_OPS_OSRELEASE_FILE: path.join(root, 'osrelease'),
      LND_OPS_MNT_ROOT: mounts,
    },
  });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), path.join(mounts, 'd'));
});

test('WSL K3s permits in-cluster API access and requires the Windows firewall gate', async () => {
  const source = await readFile(path.join(repo, 'ops/bootstrap'), 'utf8');
  assert.doesNotMatch(source, /bind-address: 127\.0\.0\.1/);
  assert.match(source, /tls-san-security: true/);
  const hostState = await readFile(path.join(repo, 'ops/windows-host-state.ps1'), 'utf8');
  assert.match(hostState, /lnd-ops-block-k3s-api/);
  assert.match(hostState, /LocalPort -notcontains '6443'/);
});

test('remote WSL log access is key-only and scoped to the operator Mac', async () => {
  const source = await readFile(path.join(repo, 'ops/windows-enable-log-access'), 'utf8');
  assert.match(source, /PasswordAuthentication no/);
  assert.match(source, /PermitRootLogin no/);
  assert.match(source, /remoteip="\$allowed_client_ip"/);
  assert.match(source, /connectport=22/);
  assert.match(source, /ssh-keygen -l/);
  assert.match(source, /sshd -T -C/);
  assert.match(source, /install -d -m 0755 \/run\/sshd/);
  assert.match(source, /ip -4 route get 1\.1\.1\.1/);
  assert.match(source, /\/mnt\/c\/Windows\/System32\/\$name/);
  assert.match(source, /--linux-user/);
  assert.match(source, /user=\$linux_user/);
  assert.doesNotMatch(source, /PRIVATE KEY/);
});
