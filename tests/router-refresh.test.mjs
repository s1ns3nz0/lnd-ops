import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = resolve(fileURLToPath(new URL('..', import.meta.url)));

test('WSL Router forwarding refreshes through a systemd service', async () => {
  const source = await readFile(resolve(repo, 'ops/windows-install-router-refresh'), 'utf8');
  assert.match(source, /lnd-ops-router-refresh\.service/);
  assert.match(source, /After=network-online\.target k3s\.service/);
  assert.match(source, /ExecStart=.*windows-enable-router/);
  assert.match(source, /Restart=on-failure/);
  assert.match(source, /systemctl enable --now/);
});
