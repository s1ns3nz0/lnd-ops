import assert from 'node:assert/strict';
import {execFileSync, spawnSync} from 'node:child_process';
import {chmod, readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import test from 'node:test';

const repo = resolve(import.meta.dirname, '..');
const demo = resolve(repo, 'ops/demo');

test('Phase 9 demo lists seven cumulative color-coded stages', async () => {
  await chmod(demo, 0o755);
  const source = await readFile(demo, 'utf8');
  const output = execFileSync(demo, ['--list', '--no-color'], {cwd: repo, encoding: 'utf8'});
  for (let stage = 1; stage <= 7; stage += 1) assert.match(output, new RegExp(`\\[${stage}/7\\]`));
  assert.match(output, /어느 단계까지|선택하면 1단계부터/);
  assert.match(output, /regtest NetworkPolicy/);
  assert.match(output, /7단계는 일회성 보안 probe Pod/);
  assert.equal((source.match(/\\033\[/g) ?? []).length >= 7, true);
});

test('Phase 9 emits a distinct ANSI color for every stage when color is forced', () => {
  const environment = {...process.env, FORCE_COLOR: '1'};
  delete environment.NO_COLOR;
  const output = execFileSync(demo, ['--list'], {
    cwd: repo,
    encoding: 'utf8',
    env: environment,
  });
  const colors = [36, 34, 35, 33, 32, 96, 95];
  colors.forEach((color, index) => {
    assert.match(output, new RegExp(`\\u001b\\[1m\\u001b\\[${color}m\\[${index + 1}/7\\]`));
  });
});

test('Phase 9 dry run stops at the selected stage and makes no changes', () => {
  const output = execFileSync(demo, ['--to', '3', '--dry-run', '--no-color'], {cwd: repo, encoding: 'utf8'});
  assert.match(output, /ops\/doctor/);
  assert.match(output, /ops\/testnet-status/);
  assert.match(output, /ops\/verify-monitoring --profile testnet/);
  assert.match(output, /ops\/verify-dashboards/);
  assert.doesNotMatch(output, /RUN ops\/exercise-phase7-agent/);
  assert.match(output, /DRY RUN 완료/);
});

test('Phase 9 rejects an invalid target before running a command', () => {
  const result = spawnSync(demo, ['--to', '8', '--dry-run', '--no-color'], {cwd: repo, encoding: 'utf8'});
  assert.equal(result.status, 2);
  assert.match(result.stderr, /invalid choice/);
});

test('Phase 9 evidence contract excludes secret values and funded mutations', async () => {
  const source = await readFile(demo, 'utf8');
  assert.match(source, /lnd-ops\/phase9-demo\/v1/);
  assert.match(source, /"secrets_recorded": False/);
  assert.match(source, /"testnet_wallet_or_channel_mutation": "excluded-by-stage-contract"/);
  assert.match(source, /reversible-security-probes/);
  assert.match(source, /process\.wait\(timeout=180\)/);
  assert.match(source, /seven-day rehearsal window/);
  for (const forbidden of ['wallet_password', 'cipher_seed', 'payment_request', 'macaroon_hex']) {
    assert.doesNotMatch(source, new RegExp(`['"]${forbidden}['"]\\s*:`));
  }
});

test('Phase 9 validates public pass markers and the seven-day evidence window', () => {
  execFileSync('python3', ['-c', "import datetime,runpy; d=runpy.run_path('ops/demo'); d['verify_public_evidence'](datetime.date(2026,9,24))"], {cwd: repo});
  const stale = spawnSync('python3', ['-c', "import datetime,runpy; d=runpy.run_path('ops/demo'); d['verify_public_evidence'](datetime.date(2026,10,2))"], {cwd: repo, encoding: 'utf8'});
  assert.notEqual(stale.status, 0);
  assert.match(stale.stderr, /seven-day rehearsal window/);
});
