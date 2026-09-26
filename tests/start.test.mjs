import assert from 'node:assert/strict';
import {execFileSync, spawnSync} from 'node:child_process';
import {chmod, readFile, rm} from 'node:fs/promises';
import {resolve} from 'node:path';
import test from 'node:test';

const repo = resolve(import.meta.dirname, '..');
const start = resolve(repo, 'ops/start');
const command = resolve(repo, 'lndops');

test('lndops is the repository command that delegates to the guided shell', async () => {
  await chmod(command, 0o755);
  const bin = resolve(repo, '.test-bin');
  const output = execFileSync(command, ['--list'], {cwd: repo, encoding: 'utf8', env: {...process.env, XDG_BIN_HOME: bin}});
  assert.match(output, /LND OPS SETUP/);
  assert.match(await readFile(command, 'utf8'), /ops\/start/);
  assert.match(await readFile(resolve(bin, 'lndops'), 'utf8'), /ops\/start/);
  await rm(bin, {recursive: true, force: true});
});

test('lndops rejects deletion verbs before it enters the setup shell', () => {
  for (const verb of ['cleanup', 'reset', 'reset-disposable', 'destroy']) {
    const result = spawnSync(command, [verb], {cwd: repo, encoding: 'utf8'});
    assert.equal(result.status, 2);
    assert.match(result.stderr, /never deletes resources/);
  }
});

test('guided setup lists all cumulative phases and the requested ASCII banner', async () => {
  await chmod(start, 0o755);
  const output = execFileSync(start, ['--list'], {cwd: repo, encoding: 'utf8'});
  for (let phase = 0; phase <= 9; phase += 1) assert.match(output, new RegExp(`\\[${phase}\\]`));
  assert.match(output, /__\s+__\s+______/);
  assert.match(output, /WALLET STATUS/);
  assert.match(output, /Mac·WSL 재현성/);
  assert.match(output, /COMMANDS/);
  assert.match(output, /delete     삭제할 project resource를 직접 선택/);
  assert.match(output, /=+/);
});

test('guided setup previews only safe automatic work and stops at the first manual gate', () => {
  const output = execFileSync(start, ['--to', '2', '--dry-run'], {cwd: repo, encoding: 'utf8'});
  assert.match(output, /PLAN ops\/doctor/);
  assert.match(output, /KUBECONFIG:/);
  assert.match(output, /PLAN ops\/bootstrap/);
  assert.match(output, /PLAN ops\/deploy regtest/);
  assert.match(output, /STOP Loop 유동성 관리 — manual phase/);
  assert.match(output, /ops\/enable-loop --macaroon \/secure\/path\/loop\.macaroon/);
  assert.doesNotMatch(output, /PLAN ops\/deploy-monitoring/);
});

test('guided setup treats an existing failed Kubernetes phase as partial', async () => {
  const contents = await readFile(start, 'utf8');
  assert.match(contents, /existing Kubernetes resources did not pass verification/);
  assert.match(contents, /\["kubectl", "get", "namespace", namespace\]/);
  assert.match(contents, /post-build verification/);
  assert.match(contents, /ops\/wallet-status/);
  assert.match(contents, /return "failed", detail\[-1\]/);
});

test('guided setup validates target numbers and refuses noninteractive unspecified input', () => {
  const invalid = spawnSync(start, ['--to', '10'], {cwd: repo, encoding: 'utf8'});
  assert.equal(invalid.status, 2);
  assert.match(invalid.stderr, /invalid choice/);
  const unavailable = spawnSync(start, [], {cwd: repo, encoding: 'utf8', input: ''});
  assert.equal(unavailable.status, 2);
  assert.match(unavailable.stderr, /interactive input unavailable/);
});

test('guided setup has an explicit wallet-preserving automatic command allowlist', async () => {
  const contents = await readFile(start, 'utf8');
  const allowlist = contents.match(/SAFE_AUTOMATIC_COMMANDS = frozenset\(\{[\s\S]*?\}\)/)?.[0] ?? '';
  assert.match(allowlist, /ops\/deploy/);
  assert.match(contents, /refusing a non-preserving automatic command/);
  assert.match(contents, /wallet_pvc_snapshot/);
  assert.match(contents, /wallet PVC identity changed during/);
  for (const unsafe of ['ops/reset-disposable', 'ops/create-testnet-wallet', 'ops/create-regtest-wallet', 'ops/exercise-regtest', 'ops/exercise-phase6-faults']) {
    assert.doesNotMatch(allowlist, new RegExp(unsafe));
  }
});

test('guided setup persists a named wallet workspace and refuses an identity change', async () => {
  const contents = await readFile(start, 'utf8');
  assert.match(contents, /lnd-ops\/wallet-selection\/v1/);
  assert.match(contents, /wallet_pvc_snapshot/);
  assert.match(contents, /PVC identity가 바뀌었습니다/);
  assert.match(contents, /wallet workspace 선택/);
});

test('interactive setup presents workspace selection before wallet status and the phase menu', async () => {
  const contents = await readFile(start, 'utf8');
  const repl = contents.slice(contents.indexOf('def repl():'), contents.indexOf('\ndef parse_args'));
  assert.doesNotMatch(repl, /if load_selection\(\) is None/);
  assert.ok(repl.indexOf('prompt_wallet_selection()') < repl.indexOf('print_wallet_overview()'));
  assert.ok(repl.indexOf('print_wallet_overview()') < repl.indexOf('print_phase_catalog()'));
});

test('wallet workspace prompt asks whether to retain a saved selection', async () => {
  const contents = await readFile(start, 'utf8');
  assert.match(contents, /현재 선택 유지/);
  assert.match(contents, /선택 \[1-4, Enter=유지\]/);
});

test('wallet workspace prompt exits cleanly on end of input', async () => {
  const contents = await readFile(start, 'utf8');
  assert.match(contents, /except EOFError:\n            print\(\)\n            return False/);
  assert.match(contents, /if not prompt_wallet_selection\(\):\n        return 0/);
});

test('delete menu trims comma-separated selections and asks before deleting wallet PVCs', async () => {
  const contents = await readFile(start, 'utf8');
  assert.match(contents, /item\.strip\(\) for item in input\("쉼표로 입력/);
  assert.match(contents, /지갑 PVC도 삭제합니까/);
  assert.match(contents, /--delete-wallet-data/);
  assert.match(contents, /wallet-data/);
});
