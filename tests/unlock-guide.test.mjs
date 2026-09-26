import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = resolve(fileURLToPath(new URL('..', import.meta.url)));

test('guided testnet phase opens the existing wallet unlock flow', async () => {
  const source = await readFile(resolve(repo, 'ops/start'), 'utf8');
  assert.match(source, /def run_testnet_unlock/);
  assert.match(source, /ops\/unlock-testnet/);
  assert.match(source, /기존 testnet 지갑 암호를 입력하면 unlock을 실행합니다/);
  assert.match(source, /지갑 데이터는 변경하지 않았습니다/);
});
