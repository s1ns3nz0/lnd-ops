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
  for (let phase = 0; phase <= 11; phase += 1) assert.match(output, new RegExp(`\\[${phase}\\]`));
  assert.match(output, /__\s+__\s+______/);
  assert.match(output, /WALLET STATUS/);
  assert.match(output, /Mac·WSL 재현성/);
  assert.match(output, /COMMANDS/);
  assert.match(output, /delete     삭제할 project resource를 직접 선택/);
  assert.match(output, /=+/);
});

test('guided setup stops its preview at the first incomplete operator phase', () => {
  const output = execFileSync(start, ['--to', '4', '--dry-run'], {cwd: repo, encoding: 'utf8'});
  assert.match(output, /PLAN ops\/doctor/);
  assert.match(output, /KUBECONFIG:/);
  assert.match(output, /PLAN ops\/bootstrap/);
  assert.match(output, /PLAN ops\/deploy regtest/);
  assert.match(output, /PENDING testnet Router Node 전환 — manual phase/);
  assert.match(output, /PHASE 03 · OPERATOR STEP/);
  assert.match(output, /공개 주소로 Lightning P2P 포트만 연결/);
  assert.match(output, /PAUSE: Phase 03/);
  assert.doesNotMatch(output, /ops\/enable-router/);
  assert.doesNotMatch(output, /PLAN ops\/deploy-monitoring/);
});

test('interactive phases execute one needed action and recheck before progressing', async () => {
  const contents = await readFile(start, 'utf8');
  assert.match(contents, /def phase_checkpoint\(number, phase\):/);
  assert.match(contents, /def operator_message\(phase, detail\):/);
  assert.match(contents, /run_testnet_unlock\(\)/);
  assert.match(contents, /if after != "complete":\n\s+return pause\(number, phase\)/);
  assert.match(contents, /현재 작업이 끝나야 다음 Phase로 진행합니다/);
  assert.doesNotMatch(contents, /위 수동 실습 gate가 남아 있습니다/);
});

test('Router progress updates a compact status block without appending poll output', async () => {
  const contents = await readFile(start, 'utf8');
  const routerGuide = contents.slice(contents.indexOf('def guide_router'), contents.indexOf('\ndef run_confirmed'));
  assert.match(routerGuide, /PHASE 03 · ROUTER PROGRESS/);
  assert.match(routerGuide, /while True:/);
  assert.match(routerGuide, /time\.sleep\(ROUTER_POLL_SECONDS\)/);
  assert.match(routerGuide, /router_active_public_channels\(\)/);
  assert.match(routerGuide, /render_router_wait\(/);
  assert.doesNotMatch(routerGuide, /확인 \{attempts/);
  assert.doesNotMatch(routerGuide, /초 뒤 Router 상태를 다시 확인/);
  assert.doesNotMatch(routerGuide, /상태 변경:/);
  assert.match(routerGuide, /공개 Router 조건과 실제 forwarding이 검증되었습니다/);
  assert.match(contents, /공개 채널       \{channel_state\}/);
  assert.match(contents, /대기 조건       \{router_wait_message/);
  assert.match(contents, /최근 채널 동기화 \{synced\}/);
  assert.match(contents, /경과 시간       \{elapsed_time/);
  assert.match(contents, /if previous == current:/);
  assert.match(contents, /zip\(previous_lines\[:3\], lines\[:3\]\)/);
  assert.match(contents, /fit_terminal_line\(line, columns\)/);
  assert.match(routerGuide, /close_router_wait\(previous_lines\)/);
});

test('every learning phase has a live completion probe and an interactive route', async () => {
  const contents = await readFile(start, 'utf8');
  for (const probe of [
    'verify-regtest-workflow', 'verify-testnet-readiness', 'verify-router', 'verify-loop',
    'verify-monitoring", "--profile", "testnet', 'phase4-acceptance', 'phase5-acceptance',
    'phase6-acceptance', 'phase7-acceptance', 'verify-phase-evidence", "phase8',
    'verify-phase-evidence", "phase9',
  ]) assert.match(contents, new RegExp(probe));
  for (const guide of ['guide_regtest', 'guide_testnet', 'guide_router', 'guide_loop', 'guide_monitoring', 'guide_evidence_phase']) {
    assert.match(contents, new RegExp(`def ${guide}`));
  }
  assert.match(contents, /run_confirmed\(/);
  assert.match(contents, /wait_for_phase\(/);
});

test('persistent testnet readiness accepts established payment history', async () => {
  const contents = await readFile(resolve(repo, 'ops/verify-testnet-readiness'), 'utf8');
  assert.match(contents, /item\.get\("status"\) == "SUCCEEDED" for item in payments/);
  assert.match(contents, /item\.get\("state"\) == "SETTLED" for item in invoices/);
  assert.doesNotMatch(contents, /within the last hour/);
});

test('monitoring still requires fresh one-hour payment samples', async () => {
  const contents = await readFile(resolve(repo, 'ops/verify-monitoring'), 'utf8');
  assert.match(contents, /lnd_ops_outgoing_payments_1h/);
  assert.match(contents, /lnd_ops_received_invoices_1h/);
  assert.match(contents, /make a fresh outgoing and incoming/);
});

test('guided setup reserves partial status for an explicit operator gate', async () => {
  const contents = await readFile(start, 'utf8');
  assert.match(contents, /if result\.returncode == 10:\n        detail = \(result\.stderr or result\.stdout\)/);
  assert.match(contents, /return "partial", detail\[-1\]/);
  assert.doesNotMatch(contents, /existing Kubernetes resources did not pass verification/);
  assert.match(contents, /post-build verification/);
  assert.match(contents, /ops\/wallet-status/);
  assert.match(contents, /return "failed", summary/);
});

test('guided setup validates target numbers and refuses noninteractive unspecified input', () => {
  const invalid = spawnSync(start, ['--to', '12'], {cwd: repo, encoding: 'utf8'});
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

test('wallet workspace prompt keeps a saved selection without advertising an Enter shortcut', async () => {
  const contents = await readFile(start, 'utf8');
  assert.match(contents, /if not answer and selected:/);
  assert.match(contents, /선택 \[1-4\]:/);
  assert.doesNotMatch(contents, /선택 \[1-4, Enter=유지\]/);
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

test('Phase zero is a resource and next-action status view', async () => {
  const contents = await readFile(start, 'utf8');
  assert.match(contents, /CURRENT RESOURCES/);
  assert.match(contents, /자동 구축과 검증이 모두 완료됨/);
  assert.match(contents, /예상하지 못한 검증 오류/);
  assert.match(contents, /\("statefulsets", "deployments", "daemonsets"\)/);
  assert.match(contents, /NEXT COMPLETION/);
  assert.match(contents, /if target == 0:/);
});
