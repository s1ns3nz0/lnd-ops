import assert from 'node:assert/strict';
import {execFileSync, spawnSync} from 'node:child_process';
import {chmod} from 'node:fs/promises';
import {resolve} from 'node:path';
import test from 'node:test';

const repo = resolve(import.meta.dirname, '..');
const purge = resolve(repo, 'ops/purge-project');

test('project purge previews only the selected namespaces', async () => {
  await chmod(purge, 0o755);
  const output = execFileSync(purge, ['--select', 'testnet,monitoring', '--dry-run'], {cwd: repo, encoding: 'utf8'});
  assert.match(output, /lnd-testnet/);
  assert.match(output, /lnd-monitoring/);
  assert.match(output, /K3s.*excluded/);
  assert.doesNotMatch(output, /lnd-regtest/);
});

test('project purge requires the exact selected-item confirmation phrase', () => {
  const result = spawnSync(purge, ['--select', 'testnet', '--confirm', 'DELETE monitoring'], {cwd: repo, encoding: 'utf8'});
  assert.equal(result.status, 2);
  assert.match(result.stderr, /DELETE testnet/);
});
