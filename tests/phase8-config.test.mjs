import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import test from 'node:test';

const repo = resolve(import.meta.dirname, '..');
const read = (path) => readFile(resolve(repo, path), 'utf8');

test('Phase 8 keeps the documented stable command surface executable', async () => {
  const required = [
    'ops/doctor', 'ops/bootstrap', 'ops/deploy', 'ops/deploy-monitoring',
    'ops/deploy-security', 'ops/acceptance',
  ];
  for (const path of required) {
    const source = await read(path);
    assert.match(source, /^#!\/usr\/bin\/env (?:bash|python3)/);
  }
  assert.match(await read('ops/deploy'), /regtest\|testnet/);
  assert.match(await read('ops/acceptance'), /regtest\|testnet/);
});

test('Phase 8 CI contains every platform-independent security and portability gate', async () => {
  const workflow = await read('.github/workflows/verify.yml');
  for (const required of [
    'Kubernetes schemas', 'Kyverno workload policy', 'Git history for secrets',
    'critical vulnerabilities', 'both CPU architectures', 'pinned image indexes',
  ]) assert.match(workflow, new RegExp(required, 'i'));
  for (const digest of [
    '8f0eeaaa96ba27ba1500b0e4b1c215acc358d159c62a7ecae58d7a03403287b0',
    'ced7b2be0b04250cabfe695f15307f69eb715fe23234816388af4f3812915b2a',
    'cdbb7c955abce02001a9f6c9f602fb195b7fadc1e812065883f695d1eeaba854',
    'e2b22eac59c02003d8749f5b8d9bd073b62e30fefaef5b7c8371204e0a4b0c08',
  ]) assert.match(workflow, new RegExp(`@sha256:${digest}`));
});

test('Kyverno CI fixtures exercise every enforced rule in both directions', async () => {
  const policy = await read('charts/security/kyverno-policy.yaml');
  const suite = await read('charts/security/tests/kyverno-test.yaml');
  const rules = [...policy.matchAll(/^    - name: ([a-z0-9-]+)$/gm)].map((match) => match[1]);
  assert.ok(rules.length >= 5);
  for (const rule of rules) {
    const occurrences = [...suite.matchAll(new RegExp(`rule: ${rule}`, 'g'))].length;
    assert.equal(occurrences, 2, `${rule} needs one pass and one fail expectation`);
  }
  assert.match(suite, /result: pass/);
  assert.match(suite, /result: fail/);
});

test('both master and main run the harness workflow', async () => {
  const workflow = await read('.github/workflows/harness-check.yml');
  assert.match(workflow, /- master/);
  assert.match(workflow, /- main/);
});
