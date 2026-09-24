import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = resolve(fileURLToPath(new URL('..', import.meta.url)));

test('encrypted recovery keeps the original identity stopped and plaintext off host storage', async () => {
  const prepare = await readFile(resolve(repo, 'ops/prepare-regtest-recovery'), 'utf8');
  const access = await readFile(resolve(repo, 'charts/regtest-recovery-access.yaml'), 'utf8');
  assert.match(prepare, /backup-status-encrypted/);
  assert.match(prepare, /passphrase-fd 3/);
  assert.match(prepare, /scale statefulset\/lnd-0 --replicas=0/);
  assert.match(prepare, /gpg[\s\S]*--decrypt[\s\S]*kubectl[\s\S]*tee \/data\/recovery\.backup/);
  assert.match(access, /name: allow-regtest-services-egress[\s\S]*namespace: lnd-regtest-recovery/);
  assert.match(access, /policyTypes: \[Egress\][\s\S]*app\.kubernetes\.io\/name: bitcoin[\s\S]*port: 18443/);
  assert.match(access, /policyTypes: \[Egress\][\s\S]*app\.kubernetes\.io\/name: lnd-1[\s\S]*port: 9735/);
});

test('Phase 5 acceptance requires recovery, alert restoration, and prior-phase continuity', async () => {
  const acceptance = await readFile(resolve(repo, 'ops/phase5-acceptance'), 'utf8');
  for (const proof of [
    'lnd-ops/regtest-recovery/v1',
    'lnd-ops/backup-alert-exercise/v1',
    'alertmanager_observed',
    'restored_current_metric',
    'original_pvc_uid',
    'phase4-acceptance',
  ]) assert.match(acceptance, new RegExp(proof));
});

test('backup alert exercise always restores the original telemetry record', async () => {
  const exercise = await readFile(resolve(repo, 'ops/exercise-backup-alert'), 'utf8');
  assert.match(exercise, /finally:/);
  assert.match(exercise, /patch_status\(original\)/);
  assert.match(exercise, /LndOpsSCBBackupStale/);
  assert.match(exercise, /Alertmanager/);
});
