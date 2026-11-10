/**
 * AWS access and local state for the agent scripts.
 *
 * Every AWS call is `execFile('aws', [...args])` (no shell). Error output is
 * reduced to a closed set (the AWS error code and an upper-case `Reason`), so
 * a message that quotes input is never echoed.
 */
import { execFile as nodeExecFile } from 'node:child_process';
import {
  chmodSync,
  closeSync,
  existsSync,
  fsyncSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  unlinkSync,
  writeSync,
} from 'node:fs';
import { dirname, join } from 'node:path';

const AWS_TIMEOUT_MS = 120_000;
export const AGENT_FILE_REL = '.deploy/agent.json';
export const STATE_DIR_REL = '.deploy/agent-setup';

/** An AWS CLI failure reduced to `code` and optional `reason`. */
export class AwsError extends Error {
  constructor(code, reason) {
    super(reason ? `${code} (${reason})` : code);
    this.name = 'AwsError';
    this.code = code;
    this.reason = reason;
  }
}

/** Reduce CLI stderr to `{ code, reason }`; nothing else is kept. */
export function classifyAwsError(stderr) {
  const text = String(stderr ?? '');
  const code = /An error occurred \((\w+)\)/.exec(text)?.[1];
  const reason = /Reason[=:]\s*"?([A-Z][A-Z0-9_]+)/.exec(text)?.[1];
  if (code) return { code, reason };
  if (/Unable to locate credentials|ExpiredToken|expired/i.test(text)) return { code: 'ExpiredToken' };
  if (/command not found|ENOENT/i.test(text)) return { code: 'AwsCliNotFound' };
  if (/Found invalid choice|invalid choice|usage:/i.test(text)) return { code: 'AwsCliTooOld' };
  return { code: 'AwsCallFailed' };
}

/**
 * Build the `aws(args)` function used by the scripts. It appends `--region`,
 * `--output json` and `--profile`, resolves with the parsed JSON (or `null`
 * for empty output), and rejects with an `AwsError`.
 */
export function makeAws({ region, profile, execFile = nodeExecFile }) {
  return (args) =>
    new Promise((resolve, reject) => {
      const full = [...args, '--region', region, '--output', 'json', ...(profile ? ['--profile', profile] : [])];
      execFile('aws', full, { timeout: AWS_TIMEOUT_MS, maxBuffer: 16 * 1024 * 1024 }, (error, stdout, stderr) => {
        if (error) {
          const { code, reason } = classifyAwsError(error.code === 'ENOENT' ? 'command not found' : stderr);
          reject(new AwsError(code, reason));
          return;
        }
        const s = String(stdout ?? '').trim();
        if (!s) return resolve(null);
        try {
          resolve(JSON.parse(s));
        } catch {
          resolve(null);
        }
      });
    });
}

/** Atomic write, mode 600, directory mode 700. */
export function writeFileAtomic(path, text) {
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  const tmp = `${path}.${process.pid}.tmp`;
  const fd = openSync(tmp, 'w', 0o600);
  try {
    writeSync(fd, text);
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
  try {
    renameSync(tmp, path);
    chmodSync(path, 0o600);
  } catch (e) {
    try {
      unlinkSync(tmp);
    } catch {
      /* best effort */
    }
    throw e;
  }
}

function isPlainObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

/** Read `.deploy/agent.json`. Returns `{ doc }` (`{}` when absent) or `{ error }`. */
export function readAgentFile(root) {
  const p = join(root, AGENT_FILE_REL);
  if (!existsSync(p)) return { doc: {} };
  try {
    const doc = JSON.parse(readFileSync(p, 'utf8'));
    if (!isPlainObject(doc) || ('agents' in doc && !isPlainObject(doc.agents))) return { error: `${AGENT_FILE_REL} has an unexpected structure` };
    return { doc };
  } catch {
    return { error: `${AGENT_FILE_REL} is not valid JSON` };
  }
}

/**
 * The agent recorded for `brand`: `agents.<brand>` first, then the legacy
 * top-level keys when they name that brand (or name none and the brand is the
 * default). Returns `{ rcsAgentId, region } | null`.
 */
export function lookupAgent(doc, brand, defaultBrand) {
  const e = doc.agents?.[brand];
  if (isPlainObject(e) && typeof e.rcsAgentId === 'string') return { rcsAgentId: e.rcsAgentId, region: e.region };
  const legacyBrand = typeof doc.brand === 'string' ? doc.brand : defaultBrand;
  if (typeof doc.rcsAgentId === 'string' && legacyBrand === brand) return { rcsAgentId: doc.rcsAgentId, region: doc.region };
  return null;
}

/**
 * Add `agents.<brand>` to the document. Legacy top-level keys are preserved
 * (an older `config.ts` reads only those); they are filled in only when absent.
 * Throws `Error` with a plain reason when the brand already has a different
 * agent and `replace` is not set.
 */
export function withAgent(doc, brand, rcsAgentId, region, { replace = false } = {}) {
  const current = doc.agents?.[brand];
  if (isPlainObject(current) && current.rcsAgentId && current.rcsAgentId !== rcsAgentId && !replace)
    throw new Error(`${brand} already has a different agent recorded; use --replace to overwrite it`);
  const next = { ...doc, agents: { ...(doc.agents ?? {}), [brand]: { rcsAgentId, region } } };
  if (typeof next.rcsAgentId !== 'string') {
    next.rcsAgentId = rcsAgentId;
    next.region = region;
    next.brand = brand;
  }
  return next;
}

/** Remove `brand` from the document (map entry and matching legacy keys). */
export function withoutAgent(doc, brand, rcsAgentId) {
  const next = { ...doc };
  if (isPlainObject(next.agents)) {
    const { [brand]: _gone, ...rest } = next.agents;
    next.agents = rest;
  }
  if (next.rcsAgentId === rcsAgentId) {
    delete next.rcsAgentId;
    delete next.region;
    delete next.brand;
  }
  return next;
}

export function saveAgentFile(root, doc) {
  writeFileAtomic(join(root, AGENT_FILE_REL), JSON.stringify(doc, null, 2) + '\n');
}

/** Resumable per-brand setup state (`.deploy/agent-setup/<brand>.json`). */
export function readState(root, brand) {
  const p = join(root, STATE_DIR_REL, `${brand}.json`);
  try {
    const s = JSON.parse(readFileSync(p, 'utf8'));
    return isPlainObject(s) ? s : {};
  } catch {
    return {};
  }
}
export function saveState(root, brand, state) {
  writeFileAtomic(join(root, STATE_DIR_REL, `${brand}.json`), JSON.stringify(state, null, 2) + '\n');
}
export function clearState(root, brand) {
  try {
    unlinkSync(join(root, STATE_DIR_REL, `${brand}.json`));
  } catch {
    /* already gone */
  }
}

/** One-line description of an AwsError for the user. */
export function describeAwsError(e) {
  if (!(e instanceof AwsError)) return 'unexpected error';
  const hint =
    e.code === 'ExpiredToken' || e.code === 'ExpiredTokenException'
      ? ' (sign in again)'
      : e.code === 'AwsCliTooOld'
        ? ' (upgrade to AWS CLI v2 2.35.12 or later)'
        : '';
  return `${e.message}${hint}`;
}
