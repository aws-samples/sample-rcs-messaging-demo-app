/**
 * The demo's two version numbers, in one place.
 *
 * (No shebang: Vite inlines this file into its own config bundle, where a `#!`
 * line ends up mid-line and is a syntax error. Both callers say `node` anyway.)
 *
 * The dashboard status bar shows `fe:1.0.0.42 | be:1.0.0.57`. The first three
 * segments are hand-maintained in version.json; the fourth is the number of
 * commits that have touched that half of the tree, so it advances on its own as
 * the code changes and never needs a "bump the version" commit. A commit that
 * only edits docs/ moves neither number, which is the point — the string is
 * there to answer "is the browser running the same code as the Lambdas I
 * deployed?", and docs cannot change that answer.
 *
 * Used two ways, because the two build systems can't share an import:
 *   - imported by web/vite.config.ts, which injects the frontend string into
 *     the bundle at build time (`__FE_VERSION__`);
 *   - run as a CLI by cdk/lib/anyhealth-stack.ts
 *     (`node scripts/version.mjs backend`), because cdk/tsconfig.json is
 *     CommonJS and cannot cleanly import an .mjs.
 *
 * A `+dev` suffix means the working tree has uncommitted changes in that area,
 * so the commit count understates what you're actually running. `+nogit` means
 * there was no git available to ask (a tarball download, a CI checkout with no
 * history) — the version is still well-formed, just not precise.
 */

import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

// Which paths each half is built from. `content/` counts as backend: those
// Markdown files are packaged into the Lambda asset, so editing one changes
// what the deployed backend serves.
const AREAS = {
  frontend: ['web'],
  backend: ['lambda', 'cdk', 'content'],
};

function git(args) {
  try {
    return execFileSync('git', args, {
      cwd: ROOT,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();
  } catch {
    // Not a repo, no git binary, or a shallow clone with no HEAD. All of these
    // are legitimate ways to run this sample, so none of them is an error.
    return null;
  }
}

/** `major.minor.patch.build` for 'frontend' or 'backend'. Never throws. */
export function version(area) {
  const paths = AREAS[area];
  if (!paths) throw new Error(`unknown area "${area}" (expected: ${Object.keys(AREAS).join(', ')})`);

  let base = '0.0.0';
  try {
    base = JSON.parse(readFileSync(join(ROOT, 'version.json'), 'utf8'))[area] || base;
  } catch {
    /* falls back to 0.0.0 — a missing version.json must not break a build */
  }

  const count = git(['rev-list', '--count', 'HEAD', '--', ...paths]);
  if (count === null) return `${base}.0+nogit`;
  const dirty = git(['status', '--porcelain', '--', ...paths]);
  return `${base}.${count}${dirty ? '+dev' : ''}`;
}

// CLI: `node scripts/version.mjs frontend|backend`
if (process.argv[1] && process.argv[1].endsWith('version.mjs')) {
  const area = process.argv[2];
  if (!AREAS[area]) {
    console.error(`usage: node scripts/version.mjs ${Object.keys(AREAS).join('|')}`);
    process.exit(2);
  }
  process.stdout.write(version(area));
}
