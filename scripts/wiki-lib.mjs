import {createHash} from 'node:crypto';
import {readdir, readFile} from 'node:fs/promises';
import {join, relative, resolve} from 'node:path';

export const repo = resolve(import.meta.dirname, '..');
export const wiki = join(repo, 'wiki');
export const publicDir = join(wiki, 'public');
export const requiredMetadata = ['title', 'description', 'versions', 'platforms', 'verified', 'commit', 'status', 'scope'];

export async function markdownFiles(directory = wiki) {
  const entries = await readdir(directory, {withFileTypes: true});
  const nested = await Promise.all(entries
    .filter((entry) => entry.name !== '.vitepress' && entry.name !== 'public')
    .map(async (entry) => entry.isDirectory() ? markdownFiles(join(directory, entry.name)) : [join(directory, entry.name)]));
  return nested.flat().filter((path) => path.endsWith('.md')).sort();
}

export function parsePage(source, path) {
  const match = source.match(/^---\n([\s\S]*?)\n---\n/);
  if (!match) throw new Error(`${relative(repo, path)}: frontmatter is missing`);
  const metadata = {};
  for (const line of match[1].split('\n')) {
    const item = line.match(/^([a-zA-Z][\w-]*):\s*(.*)$/);
    if (item && !['layout', 'hero', 'features'].includes(item[1])) metadata[item[1]] = item[2].trim().replace(/^['"]|['"]$/g, '');
  }
  return {metadata, body: source.slice(match[0].length)};
}

export function pageRoute(path) {
  const name = relative(wiki, path).replace(/\.md$/, '').replace(/\\/g, '/');
  return name === 'index' ? '/' : name.endsWith('/index') ? `/${name.slice(0, -6)}` : `/${name}`;
}

export function plainText(body) {
  return body
    .replace(/<ClientOnly>[\s\S]*?<\/ClientOnly>/g, '')
    .replace(/<[^>]+>/g, '')
    .replace(/```[\s\S]*?```/g, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/^#+\s*/gm, '')
    .replace(/:::[\s\S]*?:::/g, '')
    .trim();
}

export function hash(value) {
  return createHash('sha256').update(value).digest('hex');
}

export async function pages() {
  return Promise.all((await markdownFiles()).map(async (path) => {
    const source = await readFile(path, 'utf8');
    return {path, source, route: pageRoute(path), ...parsePage(source, path)};
  }));
}
