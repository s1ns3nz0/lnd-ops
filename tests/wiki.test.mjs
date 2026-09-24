import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import test from 'node:test';

const repo = resolve(import.meta.dirname, '..');

test('Wiki metadata, links, repository references, and public content are valid', () => {
  execFileSync('node', ['scripts/check-wiki.mjs'], {cwd: repo, stdio: 'pipe'});
});

test('LLM index is generated from every learning page with hashes', async () => {
  execFileSync('node', ['scripts/build-wiki-index.mjs'], {cwd: repo, stdio: 'pipe'});
  const manifest = JSON.parse(await readFile(resolve(repo, 'wiki/public/manifest.json'), 'utf8'));
  assert.equal(manifest.schemaVersion, 1);
  assert.equal(manifest.documents.length >= 15, true);
  assert.equal(manifest.documents.every((item) => /^[0-9a-f]{64}$/.test(item.sha256)), true);
  const catalog = await readFile(resolve(repo, 'wiki/public/llms.txt'), 'utf8');
  assert.match(catalog, /LND 구조와 상태/);
  assert.match(catalog, /Observe에서 Verify까지/);
});

test('Wiki uses strict Mermaid rendering and an explicit GitHub Pages base', async () => {
  const component = await readFile(resolve(repo, 'wiki/.vitepress/theme/MermaidDiagram.vue'), 'utf8');
  const config = await readFile(resolve(repo, 'wiki/.vitepress/config.mts'), 'utf8');
  assert.match(component, /securityLevel: 'strict'/);
  assert.match(config, /base: '\/lnd-ops\/'/);
  assert.match(config, /search: \{provider: 'local'\}/);
});
