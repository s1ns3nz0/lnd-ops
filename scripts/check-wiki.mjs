import {access, readFile, stat} from 'node:fs/promises';
import {dirname, relative, resolve} from 'node:path';
import {pages, repo, requiredMetadata, wiki} from './wiki-lib.mjs';

const failures = [];
const allowedStatuses = new Set(['설계됨', '자동 검증됨', '실제 환경 검증됨']);
const allPages = await pages();
const routes = new Set(allPages.map((page) => page.route));

for (const page of allPages) {
  const label = relative(repo, page.path);
  for (const field of requiredMetadata) if (!page.metadata[field]) failures.push(`${label}: missing ${field}`);
  if (page.metadata.status && !allowedStatuses.has(page.metadata.status)) failures.push(`${label}: invalid status ${page.metadata.status}`);
  if (page.metadata.verified && !/^\d{4}-\d{2}-\d{2}$/.test(page.metadata.verified)) failures.push(`${label}: verified must be YYYY-MM-DD`);
  if (page.metadata.commit && !/^[0-9a-f]{7,40}$/.test(page.metadata.commit)) failures.push(`${label}: commit must be a Git revision`);

  for (const match of page.source.matchAll(/\[[^\]]+\]\(([^)]+)\)/g)) {
    const target = match[1].split('#')[0];
    if (!target || /^(https?:|mailto:)/.test(target)) {
      const github = target.match(/^https:\/\/github\.com\/s1ns3nz0\/lnd-ops\/(?:blob|tree)\/master\/(.+)$/);
      if (github) try { await access(resolve(repo, github[1])); } catch { failures.push(`${label}: missing repository reference ${github[1]}`); }
      continue;
    }
    if (target.startsWith('/')) {
      const normalized = target.length > 1 && target.endsWith('/') ? target.slice(0, -1) : target;
      if (!routes.has(normalized)) failures.push(`${label}: missing internal route ${target}`);
    } else {
      const path = resolve(dirname(page.path), target);
      try { await access(path); } catch { failures.push(`${label}: missing relative link ${target}`); }
    }
  }

  const unsafe = [
    [/\b(?:seed|wallet_password|cipher_seed|macaroon_hex)\s*[:=]\s*\S+/i, 'credential-like assignment'],
    [/\b(?:10|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b/, 'private IPv4 address'],
  ];
  for (const [pattern, reason] of unsafe) if (pattern.test(page.source)) failures.push(`${label}: contains ${reason}`);
}

const banner = resolve(wiki, 'public/banner.png');
try {
  const info = await stat(banner);
  const data = await readFile(banner);
  if (!info.isFile() || data.subarray(0, 8).toString('hex') !== '89504e470d0a1a0a') failures.push('wiki/public/banner.png: invalid PNG');
} catch { failures.push('wiki/public/banner.png: missing'); }

if (failures.length) {
  console.error(failures.join('\n'));
  process.exit(1);
}
console.log(`Wiki checks passed for ${allPages.length} pages`);
