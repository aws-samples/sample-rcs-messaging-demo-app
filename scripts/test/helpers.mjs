/**
 * Shared helpers for the script tests. No AWS, no network: every AWS call goes
 * to an in-memory fake.
 */
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

/** Repository root, from this file's location. */
export const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');

const roots = [];

/**
 * A throwaway repository root: `content/`, `media/` and `cdk/` are symlinked to
 * the real ones (so the brand catalog and the yaml package resolve), and
 * `.deploy/` is private to the test.
 */
export function makeRoot(agentJson) {
  const r = mkdtempSync(join(tmpdir(), 'rcs-scripts-test-'));
  roots.push(r);
  for (const d of ['content', 'media', 'cdk']) symlinkSync(join(REPO, d), join(r, d));
  if (agentJson) {
    mkdirSync(join(r, '.deploy'), { recursive: true });
    writeFileSync(join(r, '.deploy', 'agent.json'), JSON.stringify(agentJson));
  }
  return r;
}

export function cleanupRoots() {
  for (const r of roots.splice(0)) rmSync(r, { recursive: true, force: true });
}

/** A well-formed fake agent id. */
export const agentId = (n) => `rcs-${String(n).padStart(32, '0')}`;

/** Captured stdout/stderr plus no-op sleep, for a script's `deps`. */
export function io(extra = {}) {
  const o = { out: '', err: '' };
  return { o, deps: { out: (x) => (o.out += x), err: (x) => (o.err += x), sleep: async () => {}, isTTY: false, ...extra } };
}

/** Calls that change something in AWS. */
export const mutating = (calls) => calls.filter(([op]) => /^(create|update|put|submit|delete)/.test(op));
