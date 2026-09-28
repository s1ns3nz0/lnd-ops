import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const repo = resolve(fileURLToPath(new URL('..', import.meta.url)));

function render(...extra) {
  return spawnSync('helm', [
    'template', 'lnd-ops', 'charts/lnd-ops', '-n', 'lnd-testnet',
    '-f', 'charts/lnd-ops/values-testnet.yaml', '--set-string', 'loop.image=localhost/lnd-ops-loop:test-fixture', ...extra,
  ], { cwd: repo, encoding: 'utf8' });
}

test('Phase 2 Loop is opt-in and uses checksum-pinned native release binaries', async () => {
  const values = await readFile(resolve(repo, 'charts/lnd-ops/values.yaml'), 'utf8');
  const lock = JSON.parse(await readFile(resolve(repo, 'ops/images.lock.json'), 'utf8'));
  assert.match(values, /loop:[\s\S]*enabled: false/);
  assert.match(values, /image: "" # ops\/deploy supplies the verified native release image/);
  const releases = JSON.parse(await readFile(resolve(repo, 'loop-image/releases.json'), 'utf8'));
  assert.match(releases.archives.arm64, /^[0-9a-f]{64}$/);
  assert.match(releases.archives.amd64, /^[0-9a-f]{64}$/);
  assert.equal(render().status, 0);
  assert.doesNotMatch(render().stdout, /name: loopd/);
});

test('Phase 2 Loop mounts only its dedicated credential Secret and exposes health metrics', () => {
  const rendered = render('--set', 'loop.enabled=true', '--set', 'monitoring.enabled=true');
  assert.equal(rendered.status, 0, rendered.stderr);
  assert.match(rendered.stdout, /name: loopd/);
  assert.match(rendered.stdout, /secretName: lnd-loop-credentials/);
  assert.match(rendered.stdout, /mountPath: \/credentials[\s\S]*readOnly: true/);
  assert.match(rendered.stdout, /mountPath: \/data/);
  assert.match(rendered.stdout, /claimName: loop-data/);
  assert.match(rendered.stdout, /name: loop-health/);
  assert.match(rendered.stdout, /name: lnd-loop-health/);
});

test('Phase 2 Loop network policy limits RPC and external swap traffic', () => {
  const rendered = render('--set', 'loop.enabled=true');
  assert.equal(rendered.status, 0, rendered.stderr);
  assert.match(rendered.stdout, /name: loop-to-lnd-rpc[\s\S]*port: 10009/);
  assert.match(rendered.stdout, /name: lnd-from-loop-rpc[\s\S]*port: 10009/);
  assert.match(rendered.stdout, /name: loop-server-egress[\s\S]*port: 11010/);
});

test('Loop deployment commands require an explicit enable and disable path', async () => {
  const deploy = await readFile(resolve(repo, 'ops/deploy'), 'utf8');
  const enable = await readFile(resolve(repo, 'ops/enable-loop'), 'utf8');
  assert.match(deploy, /--loop\|--no-loop/);
  assert.match(deploy, /Loop is supported only by the persistent testnet profile/);
  assert.match(enable, /chmod 600/);
  assert.match(enable, /rollout restart deployment\/loopd/);
});

test('testnet Loop uses its testnet server and namespaced TLS certificate', async () => {
  const result = render('--set', 'loop.enabled=true');
  assert.equal(result.status, 0);
  assert.match(result.stdout, /--server.host=test\.swap\.lightning\.today:11010/);
  const health = await readFile(resolve(repo, 'charts/lnd-ops/files/loop_health.py'), 'utf8');
  assert.match(health, /\{LOOP_DIR\}\/\{NETWORK\}\/tls\.cert/);
});
