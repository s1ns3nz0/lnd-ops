import assert from 'node:assert/strict';
import {mkdtemp, mkdir, writeFile, chmod} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import test from 'node:test';

const repo = resolve(import.meta.dirname, '..');
const verifier = resolve(repo, 'ops/verify-phase-evidence');

test('Phase evidence verifier requires a current, owned passing record', async () => {
  await chmod(verifier, 0o755);
  const state = await mkdtemp(join(tmpdir(), 'lnd-ops-phase-evidence-'));
  const missing = spawnSync(verifier, ['phase8'], {cwd: repo, env: {...process.env, XDG_STATE_HOME: state}, encoding: 'utf8'});
  assert.equal(missing.status, 10);
  const evidence = join(state, 'lnd-ops', 'evidence');
  await mkdir(evidence, {recursive: true, mode: 0o700});
  const record = join(evidence, 'phase8-acceptance-test.json');
  await writeFile(record, JSON.stringify({
    schema: 'lnd-ops/phase8-acceptance/v1', result: 'pass', checked_at: new Date().toISOString(),
  }));
  await chmod(record, 0o600);
  const incomplete = spawnSync(verifier, ['phase8'], {cwd: repo, env: {...process.env, XDG_STATE_HOME: state}, encoding: 'utf8'});
  assert.equal(incomplete.status, 1, incomplete.stderr);
  assert.match(incomplete.stderr, /host evidence references/);
  await writeFile(record, JSON.stringify({
    schema: 'lnd-ops/phase8-acceptance/v1', result: 'pass', checked_at: new Date().toISOString(),
    hosts: Object.fromEntries(['mac-arm64', 'windows-wsl2-amd64'].map(host => [host, {evidence: `${host}.json`, sha256: 'a'.repeat(64)}])),
    cross_platform_runtime: 'pass', standard_command_surface: 'pass', secrets_recorded: false,
  }));
  const bin = join(state, 'bin');
  await mkdir(bin);
  await writeFile(join(bin, 'kubectl'), '#!/bin/sh\nexit 1\n', {mode: 0o755});
  const pending = spawnSync(verifier, ['phase8'], {
    cwd: repo, env: {...process.env, XDG_STATE_HOME: state, PATH: `${bin}:${process.env.PATH}`}, encoding: 'utf8',
  });
  assert.equal(pending.status, 10, pending.stderr);
  assert.match(pending.stderr, /Router 운영 증거가 미완료/);
});
