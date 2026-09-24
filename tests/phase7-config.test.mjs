import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import test from 'node:test';

const repo = resolve(import.meta.dirname, '..');
const read = (path) => readFile(resolve(repo, path), 'utf8');

test('Phase 7 agent binds only the constrained project gateway', async () => {
  const manifest = await read('charts/agent/templates/kagent.yaml');
  assert.match(manifest, /name: lnd-ops-runbook-gateway/);
  assert.match(manifest, /serviceAccountName: kagent-no-kubernetes-api/);
  assert.doesNotMatch(manifest, /kagent-tool-server/);
  for (const tool of ['diagnose_incident', 'get_versioned_runbook', 'execute_allowlisted_response']) {
    assert.match(manifest, new RegExp(`- ${tool}`));
  }
});

test('Phase 7 gateway has one named mutation and explicit forbidden checks', async () => {
  const resources = await read('charts/agent/templates/resources.yaml');
  const acceptance = await read('ops/phase7-acceptance');
  assert.match(resources, /resourceNames: \[runbook-diagnostic-probe\][\s\S]*verbs: \[get, patch\]/);
  assert.doesNotMatch(resources, /verbs: \["\*"\]|resources: \["\*"\]/);
  for (const resource of ['persistentvolumeclaims', 'secrets', 'networkpolicies']) {
    assert.match(acceptance, new RegExp(resource));
  }
});

test('Phase 7 uses pinned kagent artifacts and external Ollama input', async () => {
  const deploy = await read('ops/deploy-agent');
  const sums = await read('charts/vendor/SHA256SUMS');
  const values = await read('charts/kagent-values.yaml');
  assert.match(deploy, /KAGENT_VERSION = "0\.9\.12"/);
  assert.match(deploy, /--endpoint/);
  assert.match(deploy, /--server-cidr/);
  assert.match(deploy, /allow-insecure-http/);
  assert.match(sums, /kagent-0\.9\.12\.tgz/);
  assert.match(sums, /kagent-crds-0\.9\.12\.tgz/);
  assert.equal([...values.matchAll(/@sha256:[0-9a-f]{64}/g)].length, 5);
});

test('Phase 7 chart renders', () => {
  execFileSync('helm', ['lint', 'charts/agent', '--namespace', 'lnd-agent'], {cwd: repo, stdio: 'pipe'});
  execFileSync('helm', ['template', 'lnd-ops-agent', 'charts/agent', '--namespace', 'lnd-agent'], {cwd: repo, stdio: 'pipe'});
});
