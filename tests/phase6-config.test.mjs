import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = resolve(fileURLToPath(new URL('..', import.meta.url)));

test('Phase 6 uses real production alerts and restores every injected fault', async () => {
  const exercise = await readFile(resolve(repo, 'ops/exercise-phase6-faults'), 'utf8');
  for (const alert of ['LndOpsChannelInactive', 'LndOpsPodNotReady', 'LndOpsFalcoRuntimeEvent']) {
    assert.match(exercise, new RegExp(alert));
  }
  assert.match(exercise, /finally:[\s\S]*original_spec/);
  assert.match(exercise, /delete["'], ["']pod["']/);
  assert.match(exercise, /wait_alert_clear/);
  assert.match(exercise, /lnd-ops\/phase6-faults\/v1/);
});

test('Phase 6 acceptance requires three fault classes and Phase 5 continuity', async () => {
  const acceptance = await readFile(resolve(repo, 'ops/phase6-acceptance'), 'utf8');
  for (const kind of ['lightning', 'kubernetes', 'security']) assert.match(acceptance, new RegExp(kind));
  assert.match(acceptance, /phase5-acceptance/);
  assert.match(acceptance, /signal_at.*alert_at.*runbook.*healthy_at.*alert_cleared_at/s);
  assert.match(acceptance, /lnd-ops\/phase6-acceptance\/v1/);
});
