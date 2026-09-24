import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const repo = resolve(fileURLToPath(new URL('..', import.meta.url)));

test('Phase 4 policy and network baseline are enforced', async () => {
  const policy = await readFile(resolve(repo, 'charts/security/kyverno-policy.yaml'), 'utf8');
  assert.match(policy, /validationFailureAction: Enforce/);
  for (const rule of ['require-digest-pinned-approved-images', 'require-resources', 'require-container-confinement', 'require-runtime-default-seccomp', 'deny-host-and-privileged-access']) {
    assert.match(policy, new RegExp(`name: ${rule}`));
  }
  const network = await readFile(resolve(repo, 'charts/lnd-ops/templates/networkpolicy.yaml'), 'utf8');
  assert.match(network, /policyTypes: \[Ingress, Egress\]/);
  assert.match(network, /name: allow-dns/);
  assert.match(network, /name: testnet-public-traffic/);
  assert.match(network, /name: default-deny/);
});

test('security chart runtime images render with locked digests', async () => {
  const lock = JSON.parse(await readFile(resolve(repo, 'ops/helm-plugins/lnd-ops-security-images/images.lock.json'), 'utf8'));
  assert.ok(Object.keys(lock).length >= 10);
  for (const image of Object.values(lock)) assert.match(image, /@sha256:[0-9a-f]{64}$/);
  const rendered = spawnSync('helm', ['template', 'falco', 'charts/vendor/falco-9.2.0.tgz', '-n', 'falco', '-f', 'charts/security/falco-values.yaml'], { cwd: repo, encoding: 'utf8' });
  assert.equal(rendered.status, 0, rendered.stderr);
  const pinned = spawnSync(resolve(repo, 'ops/helm-plugins/lnd-ops-security-images/render.py'), { cwd: repo, input: rendered.stdout, encoding: 'utf8' });
  assert.equal(pinned.status, 0, pinned.stderr);
  assert.match(pinned.stdout, /falcosecurity\/falco@sha256:[0-9a-f]{64}/);
  assert.match(pinned.stdout, /falcosecurity\/falcosidekick@sha256:[0-9a-f]{64}/);
});

test('security verification covers denial and runtime delivery paths', async () => {
  const verifier = await readFile(resolve(repo, 'ops/verify-security'), 'utf8');
  for (const proof of ['security-unpinned', 'security-no-resources', 'security-privileged', 'auth", "can-i', 'lnd-ops-network-probe', 'modern bpf', 'LndOpsFalcoRuntimeEvent', 'lnd_ops_tls_certificate_expiry_timestamp_seconds']) {
    assert.ok(verifier.toLowerCase().includes(proof.toLowerCase()), `missing proof: ${proof}`);
  }
});
