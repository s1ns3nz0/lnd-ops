import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = resolve(fileURLToPath(new URL('..', import.meta.url)));
const required = new Set([
  'lnd-ops-overview.json',
  'lnd-ops-node-channel.json',
  'lnd-ops-payments-liquidity.json',
  'kubernetes.json',
  'lnd-ops-security.json',
  'lnd-ops-backup-recovery.json',
]);

test('Phase 3 dashboards have unique identities and PromQL for every panel', async () => {
  const directory = resolve(repo, 'charts/dashboards');
  const names = new Set((await readdir(directory)).filter((name) => name.endsWith('.json')));
  for (const name of required) assert.ok(names.has(name), `missing ${name}`);
  const uids = new Set();
  for (const name of required) {
    const dashboard = JSON.parse(await readFile(resolve(directory, name), 'utf8'));
    assert.ok(dashboard.uid && !uids.has(dashboard.uid), `missing or duplicate UID in ${name}`);
    uids.add(dashboard.uid);
    const ids = dashboard.panels.map((panel) => panel.id);
    assert.equal(ids.length, new Set(ids).size, `duplicate panel ID in ${name}`);
    for (const panel of dashboard.panels) {
      assert.ok(panel.targets?.some((target) => target.expr), `${name}: ${panel.title} has no PromQL`);
      const serialized = JSON.stringify(panel.targets);
      assert.doesNotMatch(serialized, /payment_hash|payment_request|preimage|macaroon|peer_pubkey/i);
    }
  }
});

test('every LND Ops alert references an existing runbook', async () => {
  const rules = await readFile(resolve(repo, 'charts/monitoring-rules.yaml'), 'utf8');
  const alerts = [...rules.matchAll(/^\s*- alert: (LndOps\S+)/gm)].map((match) => match[1]);
  const runbooks = [...rules.matchAll(/^\s*runbook: (docs\/runbooks\/\S+)/gm)].map((match) => match[1]);
  assert.ok(alerts.length >= 13);
  assert.equal(runbooks.length, alerts.length);
  for (const runbook of runbooks) await readFile(resolve(repo, runbook), 'utf8');
});

test('chart collector copy matches its tested canonical source', async () => {
  const canonical = await readFile(resolve(repo, 'collector/payment_metrics.py'), 'utf8');
  const chartCopy = await readFile(resolve(repo, 'charts/lnd-ops/files/payment_metrics.py'), 'utf8');
  assert.equal(chartCopy, canonical);
});
