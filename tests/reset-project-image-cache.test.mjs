import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const repo = resolve(import.meta.dirname, '..');
const script = join(repo, 'ops/reset-project-image-cache');

function executable(path, body) {
  writeFileSync(path, body, { mode: 0o755 });
}

function fixture(vmPresent) {
  const root = mkdtempSync(join(tmpdir(), 'lnd-ops-image-reset-'));
  const bin = join(root, 'bin');
  const calls = join(root, 'docker-calls');
  const state = join(root, 'images');
  spawnSync('mkdir', ['-p', bin]);
  writeFileSync(state, 'localhost/lnd-ops-payment-collector:abc\npython:lnd-ops-verified-base-arm64\n');
  executable(join(bin, 'uname'), '#!/bin/sh\necho Darwin\n');
  executable(join(bin, 'limactl'), `#!/bin/sh
if [ "$1" = list ]; then
  echo 'NAME STATUS'
  ${vmPresent ? "echo 'lnd-ops-k3s Running'" : ':'}
fi
`);
  executable(join(bin, 'docker'), `#!/bin/sh
echo "$*" >> "$MOCK_DOCKER_CALLS"
if [ "$1 $2" = 'info ' ] || [ "$1" = info ]; then exit 0; fi
if [ "$1 $2" = 'context inspect' ]; then echo 'unix:///mock/docker.sock'; exit 0; fi
if [ "$1 $2 $3" = 'image ls --format' ]; then cat "$MOCK_IMAGE_STATE"; exit 0; fi
if [ "$1 $2" = 'image rm' ]; then : > "$MOCK_IMAGE_STATE"; exit 0; fi
exit 1
`);
  return { root, bin, calls, state };
}

test('refuses image deletion while the project VM exists', () => {
  const { root, bin, calls, state } = fixture(true);
  const result = spawnSync(script, ['--confirm-cluster-removed'], {
    cwd: repo,
    env: { ...process.env, PATH: `${bin}:/usr/bin:/bin`, LIMA_HOME: join(root, 'lima'), MOCK_DOCKER_CALLS: calls, MOCK_IMAGE_STATE: state },
    encoding: 'utf8',
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /still exists/);
  assert.equal(readFileSync(state, 'utf8').includes('payment-collector'), true);
});

test('removes only named project tags after project VM removal', () => {
  const { root, bin, calls, state } = fixture(false);
  const result = spawnSync(script, ['--confirm-cluster-removed'], {
    cwd: repo,
    env: { ...process.env, PATH: `${bin}:/usr/bin:/bin`, LIMA_HOME: join(root, 'lima'), MOCK_DOCKER_CALLS: calls, MOCK_IMAGE_STATE: state },
    encoding: 'utf8',
  });
  assert.equal(result.status, 0, result.stderr);
  const invocation = readFileSync(calls, 'utf8');
  assert.match(invocation, /image rm localhost\/lnd-ops-payment-collector:abc python:lnd-ops-verified-base-arm64/);
  assert.equal(readFileSync(state, 'utf8'), '');
});
