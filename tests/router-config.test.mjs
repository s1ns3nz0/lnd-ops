import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const repo = resolve(fileURLToPath(new URL('..', import.meta.url)));

test('Router mode is opt-in and exposes only the fixed P2P NodePort', async () => {
  const values = await readFile(resolve(repo, 'charts/lnd-ops/values.yaml'), 'utf8');
  assert.match(values, /router:[\s\S]*enabled: false/);
  const off = spawnSync('helm', ['template', 'lnd-ops', 'charts/lnd-ops', '-f', 'charts/lnd-ops/values-testnet.yaml'], { cwd: repo, encoding: 'utf8' });
  assert.equal(off.status, 0, off.stderr);
  assert.doesNotMatch(off.stdout, /name: lnd-router-p2p/);
  const on = spawnSync('helm', ['template', 'lnd-ops', 'charts/lnd-ops', '-f', 'charts/lnd-ops/values-testnet.yaml', '--set', 'router.enabled=true', '--set-string', 'router.externalIP=router.example.net'], { cwd: repo, encoding: 'utf8' });
  assert.equal(on.status, 0, on.stderr);
  assert.match(on.stdout, /name: lnd-router-p2p[\s\S]*type: NodePort[\s\S]*port: 9735[\s\S]*nodePort: 30973/);
  assert.match(on.stdout, /--externalip=router\.example\.net:9735/);
  assert.doesNotMatch(on.stdout, /nodePort: 10009/);
});

test('fresh Mac VMs forward only Router host P2P to the NodePort', async () => {
  const lima = await readFile(resolve(repo, 'ops/lima.yaml.in'), 'utf8');
  assert.match(lima, /guestPort: 30973\s+hostPort: 9735\s+hostIP: 0\.0\.0\.0/);
  assert.doesNotMatch(lima, /guestPort: 10009/);
});

test('Router commands separate exposure, policy mutation, and read-only verification', async () => {
  const [enable, policy, verify, deploy] = await Promise.all([
    readFile(resolve(repo, 'ops/enable-router'), 'utf8'),
    readFile(resolve(repo, 'ops/configure-router-policy'), 'utf8'),
    readFile(resolve(repo, 'ops/verify-router'), 'utf8'),
    readFile(resolve(repo, 'ops/deploy'), 'utf8'),
  ]);
  assert.match(enable, /--external-ip PUBLIC_HOST/);
  assert.match(enable, /NodePort 30973/);
  assert.match(policy, /APPLY ROUTER POLICY/);
  assert.match(policy, /--fee_rate=0\.0005/);
  assert.match(policy, /--max_htlc_msat=/);
  assert.match(verify, /fwdinghistory/);
  assert.match(verify, /active public channel/);
  assert.match(verify, /NodePort 30973/);
  assert.match(verify, /node2_pub/);
  assert.match(verify, /local_balance.*- 1\) \* 1000/);
  assert.match(deploy, /--router --router-external-ip HOST/);
});
