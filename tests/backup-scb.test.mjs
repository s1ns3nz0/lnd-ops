import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, rm, stat, writeFile, chmod } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const repo = resolve(fileURLToPath(new URL('..', import.meta.url)));

test('SCB transfer records the verified copy and rejects unsafe permissions or stale data', async () => {
  const root = await mkdtemp(join(tmpdir(), 'lnd-ops-scb-'));
  try {
    const bin = join(root, 'bin');
    const home = join(root, 'home');
    await mkdir(bin);
    await mkdir(home);
    const source = join(root, 'source-scb');
    await writeFile(source, 'disposable backup fixture\n');
    const scripts = {
      uname: '#!/bin/sh\necho Darwin\n',
      sha256sum: `#!/usr/bin/env python3
import hashlib, sys
for path in sys.argv[1:]:
    with open(path, 'rb') as file:
        print(hashlib.sha256(file.read()).hexdigest(), ' ', path)
`,
      stat: `#!/usr/bin/env python3
import os, sys
if sys.argv[1:3] != ['-f', '%Lp']:
    raise SystemExit(2)
print(oct(os.stat(sys.argv[3]).st_mode & 0o777)[2:])
`,
      kubectl: `#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == -n && "$3" == exec && "$5" == -- ]]
case "$6" in
  test) test -s "$MOCK_SCB_SOURCE" ;;
  sha256sum) sha256sum "$MOCK_SCB_SOURCE" | awk -v path="$7" '{print $1 "  " path}' ;;
  cat) cat "$MOCK_SCB_SOURCE" ;;
  *) exit 2 ;;
esac
`,
    };
    for (const [name, body] of Object.entries(scripts)) {
      const file = join(bin, name);
      await writeFile(file, body, { mode: 0o755 });
    }
    const env = { ...process.env, HOME: home, MOCK_SCB_SOURCE: source, PATH: `${bin}:${process.env.PATH}` };
    const run = (name) => spawnSync(join(repo, 'ops', name), ['regtest', 'lnd-0'], {
      cwd: repo, env, encoding: 'utf8',
    });
    const backup = run('backup-scb');
    assert.equal(backup.status, 0, backup.stderr);
    const target = join(home, 'lnd-ops-backups/regtest/lnd-0/channel.backup');
    const record = join(home, 'lnd-ops-backups/regtest/lnd-0/.last-success');
    assert.equal((await stat(target)).mode & 0o777, 0o600);
    assert.equal((await stat(record)).mode & 0o777, 0o600);
    assert.equal(await readFile(target, 'utf8'), 'disposable backup fixture\n');
    assert.equal(run('backup-status').status, 0);

    await chmod(target, 0o644);
    assert.match(run('backup-status').stderr, /permissions are not 600/);
    await chmod(target, 0o600);
    const originalRecord = await readFile(record, 'utf8');
    await writeFile(record, `${Math.floor(Date.now() / 1000)} ${'0'.repeat(64)}\n`, { mode: 0o600 });
    assert.match(run('backup-status').stderr, /copy and transfer record differ/);
    await writeFile(record, originalRecord, { mode: 0o600 });
    await writeFile(source, 'changed source backup\n');
    assert.match(run('backup-status').stderr, /source and host copy differ/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('encrypted SCB status verifies ciphertext and current source hashes without a passphrase', async () => {
  const root = await mkdtemp(join(tmpdir(), 'lnd-ops-scb-encrypted-'));
  try {
    const bin = join(root, 'bin');
    const home = join(root, 'home');
    const directory = join(home, 'lnd-ops-backups-encrypted/regtest/lnd-0');
    await mkdir(bin, { recursive: true });
    await mkdir(directory, { recursive: true, mode: 0o700 });
    await chmod(join(home, 'lnd-ops-backups-encrypted'), 0o700);
    await chmod(join(home, 'lnd-ops-backups-encrypted/regtest'), 0o700);
    const plaintext = Buffer.from('disposable scb plaintext');
    const ciphertext = Buffer.from('encrypted fixture bytes');
    const hash = (value) => createHash('sha256').update(value).digest('hex');
    const target = join(directory, 'channel.backup.gpg');
    const record = join(directory, '.last-success');
    await writeFile(target, ciphertext, { mode: 0o600 });
    await writeFile(record, `${Math.floor(Date.now() / 1000)} ${hash(plaintext)} ${hash(ciphertext)} gpg-symmetric-v1\n`, { mode: 0o600 });
    await writeFile(join(bin, 'kubectl'), `#!/bin/sh\nprintf '${hash(plaintext)}  /data/channel.backup\\n'\n`, { mode: 0o755 });
    await writeFile(join(bin, 'stat'), `#!/usr/bin/env python3
import os, sys
assert sys.argv[1] == '-c' and sys.argv[2] == '%a'
print(oct(os.stat(sys.argv[3]).st_mode & 0o777)[2:])
`, { mode: 0o755 });
    const run = () => spawnSync(join(repo, 'ops/backup-status-encrypted'), ['regtest', 'lnd-0'], {
      cwd: repo,
      env: { ...process.env, HOME: home, PATH: `${bin}:${process.env.PATH}` },
      encoding: 'utf8',
    });
    const verified = run();
    assert.equal(verified.status, 0, verified.stderr);
    await writeFile(target, 'tampered', { mode: 0o600 });
    assert.match(run().stderr, /Encrypted SCB and transfer record differ/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
