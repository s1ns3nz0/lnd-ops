import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const repo = resolve(fileURLToPath(new URL('..', import.meta.url)));

test('disposable reset refuses deletion when wallet absence cannot be confirmed', async () => {
  const root = await mkdtemp(join(tmpdir(), 'lnd-ops-reset-'));
  try {
    const bin = join(root, 'bin');
    await mkdir(bin);
    const calls = join(root, 'kubectl-calls');
    const fake = join(bin, 'kubectl');
    await writeFile(fake, `#!/bin/sh
printf '%s\\n' "$*" >> "$MOCK_KUBECTL_CALLS"
case " $* " in
  *" test ! -e "*) exit 1 ;;
  *) exit 0 ;;
esac
`, { mode: 0o755 });
    const result = spawnSync(join(repo, 'ops/reset-disposable'), ['testnet', '--confirm-unfunded'], {
      cwd: repo,
      env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, MOCK_KUBECTL_CALLS: calls },
      encoding: 'utf8',
    });
    assert.equal(result.status, 1, result.stderr);
    assert.match(result.stderr, /wallet absence was not confirmed/);
    assert.doesNotMatch(await readFile(calls, 'utf8'), /delete namespace/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
