import {mkdir, writeFile} from 'node:fs/promises';
import {relative} from 'node:path';
import {hash, pages, plainText, publicDir, repo} from './wiki-lib.mjs';

const base = 'https://s1ns3nz0.github.io/lnd-ops';
const documents = (await pages()).map((page) => {
  const markdown = plainText(page.body);
  return {
    id: page.route === '/' ? 'home' : page.route.slice(1).replaceAll('/', '-'),
    locale: 'ko',
    section: page.route.split('/')[1] || 'start',
    title: page.metadata.title,
    description: page.metadata.description,
    url: `${base}${page.route}`,
    markdownUrl: `${base}/llms/ko${page.route === '/' ? '/index' : page.route}.md`,
    lastUpdated: page.metadata.verified,
    sha256: hash(markdown),
    bytes: Buffer.byteLength(markdown),
    source: relative(repo, page.path),
    markdown,
  };
});

await mkdir(`${publicDir}/llms/ko`, {recursive: true});
for (const document of documents) {
  const path = `${publicDir}/llms/ko${document.url === base + '/' ? '/index' : new URL(document.url).pathname.replace('/lnd-ops', '')}.md`;
  await mkdir(path.slice(0, path.lastIndexOf('/')), {recursive: true});
  await writeFile(path, `# ${document.title}\n\n> ${document.description}\n\n${document.markdown}\n`);
}

const listing = documents.map((document) => `- [${document.title}](${document.markdownUrl}): ${document.description}`).join('\n');
await writeFile(`${publicDir}/llms.txt`, `# LND Ops Wiki\n\n> LND 운영 요구를 Kubernetes 설계, 관측, 보안, runbook, kagent 대응으로 연결하는 한국어 학습 Wiki입니다.\n\n## Docs (한국어)\n\n${listing}\n`);
await writeFile(`${publicDir}/llms-full-ko.txt`, documents.map((document) => `----------------------------------------\nSource: ${document.url}\n----------------------------------------\n\n# ${document.title}\n\n${document.markdown}`).join('\n\n'));
await writeFile(`${publicDir}/manifest.json`, `${JSON.stringify({schemaVersion: 1, generatedFrom: 'tracked wiki Markdown', documents: documents.map(({markdown, ...item}) => item)}, null, 2)}\n`);
console.log(`Generated LLM index for ${documents.length} pages`);
