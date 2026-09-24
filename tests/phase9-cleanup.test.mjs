import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {chmod, link, mkdir, mkdtemp, readFile, rm, stat, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import test from 'node:test';

const repo = resolve(import.meta.dirname, '..');
const demo = resolve(repo, 'ops/demo');

async function evidence(path, checkedAt) {
  await writeFile(path, JSON.stringify({
    schema: 'lnd-ops/phase9-demo/v1', result: 'pass', checked_at: checkedAt,
  }), {mode: 0o600});
  await chmod(path, 0o600);
}

test('evidence cleanup previews, requires confirmation, and preserves newest pass', async () => {
  const root = await mkdtemp(join(tmpdir(), 'lnd-ops-demo-cleanup-'));
  try {
    const directory = join(root, 'lnd-ops/evidence');
    await mkdir(directory, {recursive: true, mode: 0o700});
    const old = join(directory, 'phase9-demo-20200101T000000.000000Z.json');
    const newest = join(directory, 'phase9-demo-20990101T000000.000000Z.json');
    await evidence(old, '2020-01-01T00:00:00Z');
    await evidence(newest, new Date().toISOString());

    const environment = {...process.env, XDG_STATE_HOME: root};
    const preview = spawnSync(demo, ['cleanup', 'evidence', '--older-than-days', '1'], {cwd: repo, env: environment, encoding: 'utf8'});
    assert.equal(preview.status, 0, preview.stderr);
    assert.match(preview.stdout, /PREVIEW ONLY/);
    assert.match(preview.stdout, /KEEP newest passing evidence/);
    assert.equal((await stat(old)).isFile(), true);

    const applied = spawnSync(demo, ['cleanup', 'evidence', '--older-than-days', '1', '--confirm'], {cwd: repo, env: environment, encoding: 'utf8'});
    assert.equal(applied.status, 0, applied.stderr);
    await assert.rejects(stat(old));
    assert.equal((await stat(newest)).isFile(), true);
    assert.equal((await stat(newest)).mode & 0o777, 0o600);
  } finally {
    await rm(root, {recursive: true, force: true});
  }
});

test('demo cleanup refuses a reserved Pod name without the expected ownership marker', async () => {
  const root = await mkdtemp(join(tmpdir(), 'lnd-ops-demo-owner-'));
  try {
    const bin = join(root, 'bin');
    const calls = join(root, 'calls');
    await mkdir(bin);
    await writeFile(join(bin, 'kubectl'), `#!/bin/sh
printf '%s\\n' "$*" >> "$MOCK_CALLS"
case " $* " in
  *" version "*) exit 0 ;;
  *" config current-context "*) echo project; exit 0 ;;
  *" config view --minify "*) echo https://127.0.0.1:6443; exit 0 ;;
  *" get namespace kube-system "*) echo cluster-uid; exit 0 ;;
  *" get namespace lnd-regtest "*) echo protected; exit 0 ;;
  *" get namespace lnd-testnet "*) echo protected; exit 0 ;;
  *" get pod phase6-crashloop "*) echo '{"metadata":{"labels":{"app.kubernetes.io/name":"someone-else"}},"spec":{"containers":[{"name":"fault"}]}}'; exit 0 ;;
  *) exit 1 ;;
esac
`, {mode: 0o755});
    const result = spawnSync(demo, ['cleanup', 'demo'], {
      cwd: repo,
      env: {...process.env, PATH: `${bin}:${process.env.PATH}`, MOCK_CALLS: calls},
      encoding: 'utf8',
    });
    assert.equal(result.status, 1);
    assert.match(result.stderr, /refusing unowned Pod/);
    assert.doesNotMatch(await readFile(calls, 'utf8'), / delete /);
  } finally {
    await rm(root, {recursive: true, force: true});
  }
});

test('environment cleanup keeps the existing explicit wallet-free confirmation gate', async () => {
  const missing = spawnSync(demo, ['cleanup', 'environment', 'testnet'], {cwd: repo, encoding: 'utf8'});
  assert.equal(missing.status, 1);
  assert.match(missing.stderr, /requires --confirm-unfunded/);
});

test('evidence cleanup refuses hard-linked records', async () => {
  const root = await mkdtemp(join(tmpdir(), 'lnd-ops-demo-hardlink-'));
  try {
    const directory = join(root, 'lnd-ops/evidence');
    await mkdir(directory, {recursive: true, mode: 0o700});
    const first = join(directory, 'phase9-demo-first.json');
    const second = join(directory, 'phase9-demo-second.json');
    await evidence(first, new Date().toISOString());
    await link(first, second);
    const result = spawnSync(demo, ['cleanup', 'evidence', '--confirm'], {
      cwd: repo, env: {...process.env, XDG_STATE_HOME: root}, encoding: 'utf8',
    });
    assert.equal(result.status, 1);
    assert.match(result.stderr, /unsafe Phase 9 evidence/);
    assert.equal((await stat(first)).isFile(), true);
  } finally {
    await rm(root, {recursive: true, force: true});
  }
});

test('Kubernetes cleanup binds deletion and policy restoration to planned identities', async () => {
  const source = await readFile(resolve(repo, 'ops/demo-cleanup'), 'utf8');
  assert.match(source, /test.*\/metadata\/uid/s);
  assert.match(source, /test.*\/metadata\/resourceVersion/s);
  assert.match(source, /lnd-ops\.dev~1cleanup-token/);
  assert.match(source, /app\.kubernetes\.io\/managed-by/);
  assert.match(source, /reconnect_regtest\(required=True, inspect_only=True\)/);
});
