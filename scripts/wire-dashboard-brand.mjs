/**
 * Wire one deployed brand into the local dashboard's brand picker.
 *
 *   node scripts/wire-dashboard-brand.mjs <Brand_Id> <REGION> [<PROFILE>]
 *   node scripts/wire-dashboard-brand.mjs --remove <Brand_Id> [<Brand_Id> ...]
 *   node scripts/wire-dashboard-brand.mjs --prune <REGION> [<PROFILE>]
 *
 * Run from the repository root. The command reads the `ApiUrl` and
 * `ApiKeySecretName` outputs of that brand's `<prefix>-rcs-demo` stack, reads the
 * API key from the named Secrets Manager secret, and merges
 * `{ apiUrl, apiKey, updatedAt }` for that brand into `.deploy/dashboard-brands.json`
 * (gitignored, mode 600). The Vite dev server reads that file on each request,
 * so a page reload shows the brand in the picker.
 *
 * Key handling: every AWS call goes through `execFile` with an argument array
 * (no shell). The key exists only as the `get-secret-value` child's stdout
 * buffer in this process and is written only to the store. It never appears on
 * any process's argv, in this script's stdout or stderr, or in shell history.
 * The child's stderr is never echoed: only an error category is printed.
 *
 * `--remove` takes brands out of the store (no AWS call): use it when you tear
 * a brand down. `--prune` removes every store entry whose CloudFormation stack
 * no longer exists, and keeps an entry whenever it cannot tell (expired
 * credentials, throttling, an unknown brand): it never removes on uncertainty.
 * Each wired entry records its `region` and `stackName` so `--prune` looks in
 * the right place; an older entry without them is checked in the Region its API
 * URL names, else in <REGION>.
 *
 * The dashboard itself lists a brand only if it can load that brand's agent
 * identity, so a stale entry is never offered. Keeping the store tidy is for
 * the next person who reads it, and keeps the check at page load fast.
 *
 * This script never opens `web/.env` or `web/.env.*`.
 *
 * Exit codes: 0 wired; 1 AWS read failed, the existing store is unreadable, or
 * the write failed (store left unchanged); 2 bad input (no AWS call made).
 *
 * The pure helpers are exported for run-and-delete checks. The CLI runs only
 * when this file is invoked directly.
 */
import { execFile as nodeExecFile } from 'node:child_process';
import {
  closeSync,
  existsSync,
  fchmodSync,
  fsyncSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  statSync,
  unlinkSync,
  writeSync,
} from 'node:fs';
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const STORE_REL = '.deploy/dashboard-brands.json';
const STORE_MAX_BYTES = 1024 * 1024;
const AWS_TIMEOUT_MS = 60_000;

/** A Brand_Id: lowercase letter, then up to 31 lowercase letters, digits or `-`. */
export function isValidBrandId(s) {
  return typeof s === 'string' && /^[a-z][a-z0-9-]{0,31}$/.test(s);
}

/**
 * Resource-name prefix from a brand name. Mirrors `slugify` in
 * `cdk/lib/brand-selection.ts` exactly (including its fallback), so the stack
 * name found here is the one `cdk deploy` created.
 */
export function slugify(name) {
  return (
    String(name)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 20) || 'anyhealth'
  );
}

function isPlainObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

/** Error from `mergeStore`; `reason` is from a closed set and quotes no file content. */
export class StoreError extends Error {
  constructor(reason) {
    super(reason);
    this.name = 'StoreError';
    this.reason = reason;
  }
}

/**
 * Merge one brand's connection into the store document.
 *
 * `existingText` is the current file content, or `null`/`undefined` when the
 * file does not exist. Returns the new file text. Exactly one entry exists for
 * `id` afterwards; every other entry and every unknown field (top level or in
 * the replaced entry) is preserved. Throws `StoreError` with reason
 * `not valid JSON` or `unexpected structure` when the existing content is not a
 * store document, so the caller never overwrites entries it could not read.
 * `JSON.parse` messages are not forwarded: they can quote the input.
 */
export function mergeStore(existingText, id, apiUrl, apiKey, now = new Date(), extra = {}) {
  const doc = parseStoreDoc(existingText);
  const previous = Object.prototype.hasOwnProperty.call(doc.brands, id) ? doc.brands[id] : {};
  const brands = { ...doc.brands };
  brands[id] = { ...previous, apiUrl, apiKey, ...extra, updatedAt: now.toISOString() };
  return JSON.stringify({ ...doc, brands }, null, 2) + '\n';
}

/**
 * Parse the store document, or start an empty one when `existingText` is
 * null/undefined. Throws `StoreError` (`not valid JSON` / `unexpected
 * structure`) so a caller never overwrites entries it could not read.
 */
function parseStoreDoc(existingText) {
  if (existingText === null || existingText === undefined) return { version: 1, brands: {} };
  let doc;
  try {
    doc = JSON.parse(existingText);
  } catch {
    throw new StoreError('not valid JSON');
  }
  if (
    !isPlainObject(doc) ||
    !isPlainObject(doc.brands) ||
    ('version' in doc && doc.version !== 1) ||
    !Object.values(doc.brands).every(isPlainObject)
  ) {
    throw new StoreError('unexpected structure');
  }
  return 'version' in doc ? doc : { version: 1, ...doc };
}

/**
 * Remove entries from the store document. Returns the new file text and the ids
 * that were actually present. Every other entry and field is preserved. Throws
 * `StoreError` like `mergeStore`.
 */
export function removeFromStore(existingText, ids) {
  const doc = parseStoreDoc(existingText);
  const brands = { ...doc.brands };
  const removed = [];
  for (const id of ids) {
    if (Object.prototype.hasOwnProperty.call(brands, id)) {
      delete brands[id];
      removed.push(id);
    }
  }
  return { text: JSON.stringify({ ...doc, brands }, null, 2) + '\n', removed };
}

/** The Region named by an HTTP API URL (`https://<id>.execute-api.<region>.amazonaws.com`), or "". */
export function regionFromApiUrl(url) {
  const m = typeof url === 'string' ? url.match(/\.execute-api\.([a-z0-9-]+)\.amazonaws\.com/) : null;
  return m ? m[1] : '';
}

/**
 * Reduce a failed AWS CLI call to an error category. Only the AWS error code
 * (a bare identifier) or a fixed label leaves this function; nothing else from
 * stderr is returned.
 *
 * @param {string} stderr     the child's stderr
 * @param {string} [errCode]  the spawn error's `code` (`ENOENT` when `aws` is missing)
 */
export function errorCategory(stderr, errCode) {
  if (errCode === 'ENOENT') return 'CLI not found';
  if (errCode === 'ETIMEDOUT') return 'timeout';
  const text = typeof stderr === 'string' ? stderr : '';
  const m = text.match(/An error occurred \(([A-Za-z0-9._-]{1,64})\)/);
  if (m) return m[1];
  if (/expired/i.test(text)) return 'ExpiredToken';
  if (/access ?denied|not authorized/i.test(text)) return 'AccessDenied';
  if (/does not exist|not found/i.test(text)) return 'NotFound';
  return 'unknown';
}

/** Promise wrapper over an injected `execFile`. Never rejects with child output. */
function run(execFile, args, env) {
  return new Promise((resolve) => {
    execFile(
      'aws',
      args,
      { env, timeout: AWS_TIMEOUT_MS, maxBuffer: 1024 * 1024, windowsHide: true },
      (err, stdout, stderr) => {
        if (err) {
          const code = err.killed || err.signal ? 'ETIMEDOUT' : err.code;
          const text = String(stderr ?? '');
          resolve({
            ok: false,
            category: errorCategory(text, code),
            // Only a boolean leaves here, never the text: CloudFormation says a
            // stack that is gone "does not exist".
            missing: /Stack with id .{1,200} does not exist/i.test(text),
          });
        } else {
          resolve({ ok: true, stdout: String(stdout ?? '') });
        }
      },
    );
  });
}

function readCatalog(root) {
  let YAML;
  try {
    YAML = createRequire(join(root, 'cdk', 'package.json'))('yaml');
  } catch {
    return { error: 'the yaml package is not installed in cdk/; run `(cd cdk && npm ci)` first' };
  }
  let fm = {};
  try {
    const raw = readFileSync(join(root, 'content', 'brand.md'), 'utf8');
    const m = raw.match(/^---\n([\s\S]*?)\n---/);
    fm = (m && YAML.parse(m[1])) || {};
  } catch {
    return { error: 'could not parse the frontmatter of content/brand.md' };
  }
  // Same fallback as cdk/lib/config.ts: a file with no `brands:` map is a
  // one-entry catalog under defaultBrand.
  const defaultBrand =
    typeof fm.defaultBrand === 'string' && fm.defaultBrand.trim() ? fm.defaultBrand.trim() : 'anyhealth';
  const brands = isPlainObject(fm.brands) ? fm.brands : { [defaultBrand]: fm };
  return { brands };
}

/**
 * Read the store file. Creates `.deploy/` (mode 700) when missing. Returns
 * `{ text }` (null when the file does not exist) or `{ error }` with a complete
 * message for stderr; never an error that quotes file content.
 */
function readStoreText(root) {
  const deployDir = join(root, '.deploy');
  const storePath = join(root, STORE_REL);
  try {
    mkdirSync(deployDir, { recursive: true, mode: 0o700 });
  } catch (e) {
    return { error: `Could not create .deploy/ (${e?.code ?? 'error'}).\n` };
  }
  try {
    if (statSync(storePath).size > STORE_MAX_BYTES) {
      return { error: `Existing ${STORE_REL} is unreadable (too large); fix or delete it.\n` };
    }
    return { text: readFileSync(storePath, 'utf8') };
  } catch (e) {
    if (e?.code !== 'ENOENT') {
      return {
        error: `Existing ${STORE_REL} is unreadable (could not be read (${e?.code ?? 'error'})); fix or delete it.\n`,
      };
    }
    return { text: null };
  }
}

/**
 * Atomic write: temp file at mode 600 from creation, fsync, rename. Returns
 * null on success or a complete message for stderr.
 */
function writeStoreText(root, text) {
  const deployDir = join(root, '.deploy');
  const storePath = join(root, STORE_REL);
  const tmp = join(deployDir, `.dashboard-brands.${process.pid}.tmp`);
  let fd;
  let created = false;
  try {
    fd = openSync(tmp, 'wx', 0o600);
    created = true;
    fchmodSync(fd, 0o600);
    const buf = Buffer.from(text, 'utf8');
    let off = 0;
    while (off < buf.length) off += writeSync(fd, buf, off, buf.length - off);
    fsyncSync(fd);
    closeSync(fd);
    fd = undefined;
    renameSync(tmp, storePath);
    created = false;
    return null;
  } catch (e) {
    if (fd !== undefined) {
      try { closeSync(fd); } catch { /* already closed */ }
    }
    if (created) {
      try { unlinkSync(tmp); } catch { /* best effort */ }
    }
    return `Could not write ${STORE_REL} (${e?.code ?? 'error'}); the existing file is unchanged.\n`;
  }
}

/** `--remove <Brand_Id> ...`: take brands out of the store. No AWS call. */
export function removeMain(ids, { root = process.cwd(), out = (s) => process.stdout.write(s), err = (s) => process.stderr.write(s) } = {}) {
  if (ids.length === 0 || !ids.every(isValidBrandId)) {
    err('usage: node scripts/wire-dashboard-brand.mjs --remove <Brand_Id> [<Brand_Id> ...]\n');
    return 2;
  }
  const existing = readStoreText(root);
  if (existing.error) {
    err(existing.error);
    return 1;
  }
  if (existing.text === null) {
    out(`Nothing to remove: ${STORE_REL} does not exist.\n`);
    return 0;
  }
  let result;
  try {
    result = removeFromStore(existing.text, ids);
  } catch (e) {
    const reason = e instanceof StoreError ? e.reason : 'unexpected structure';
    err(`Existing ${STORE_REL} is unreadable (${reason}); fix or delete it.\n`);
    return 1;
  }
  for (const id of ids) {
    out(result.removed.includes(id) ? `Removed ${id} from the dashboard.\n` : `${id}: was not in the dashboard store.\n`);
  }
  if (result.removed.length > 0) {
    const writeError = writeStoreText(root, result.text);
    if (writeError) {
      err(writeError);
      return 1;
    }
    out('Reload the dashboard.\n');
  }
  return 0;
}

/** CloudFormation stack check: "present", "missing" or "unknown" (with a reason). */
async function stackStatus(execFile, stackName, region, profileArgs, env) {
  const r = await run(
    execFile,
    ['cloudformation', 'describe-stacks', '--stack-name', stackName, '--region', region,
      ...profileArgs, '--query', 'Stacks[0].StackStatus', '--output', 'text'],
    env,
  );
  if (r.ok) return { status: 'present' };
  if (r.missing) return { status: 'missing' };
  return { status: 'unknown', reason: r.category };
}

/**
 * `--prune <REGION> [<PROFILE>]`: remove store entries whose stack no longer
 * exists. An entry is kept whenever the answer is anything but "stack does not
 * exist", so expired credentials or throttling never delete a live brand.
 */
export async function pruneMain(
  argv,
  {
    execFile = nodeExecFile,
    root = process.cwd(),
    env = process.env,
    out = (s) => process.stdout.write(s),
    err = (s) => process.stderr.write(s),
  } = {},
) {
  const [region, profile, ...extra] = argv;
  if (extra.length > 0 || typeof region !== 'string' || !/^[a-z0-9-]+$/.test(region)) {
    err('usage: node scripts/wire-dashboard-brand.mjs --prune <REGION> [<PROFILE>]\n');
    return 2;
  }
  if (profile !== undefined && profile === '') {
    err('Invalid PROFILE "": omit it or name an AWS profile.\n');
    return 2;
  }
  const catalog = readCatalog(root);
  if (catalog.error) {
    err(`Cannot read the brand catalog: ${catalog.error}.\n`);
    return 2;
  }
  const existing = readStoreText(root);
  if (existing.error) {
    err(existing.error);
    return 1;
  }
  if (existing.text === null) {
    out(`Nothing to prune: ${STORE_REL} does not exist.\n`);
    return 0;
  }
  let doc;
  try {
    doc = parseStoreDoc(existing.text);
  } catch (e) {
    const reason = e instanceof StoreError ? e.reason : 'unexpected structure';
    err(`Existing ${STORE_REL} is unreadable (${reason}); fix or delete it.\n`);
    return 1;
  }
  const profileArgs = profile !== undefined ? ['--profile', profile] : [];
  const childEnv = { ...env, AWS_PAGER: '' };

  const removed = [];
  for (const id of Object.keys(doc.brands).sort()) {
    const entry = doc.brands[id];
    const entryRegion =
      [entry.region, regionFromApiUrl(entry.apiUrl), region].find(
        (v) => typeof v === 'string' && /^[a-z0-9-]+$/.test(v),
      ) ?? region;
    let stackName =
      typeof entry.stackName === 'string' && /^[A-Za-z][A-Za-z0-9-]{0,127}$/.test(entry.stackName)
        ? entry.stackName
        : '';
    if (!stackName) {
      const block = catalog.brands[id];
      if (isPlainObject(block) && typeof block.brandName === 'string' && block.brandName.trim()) {
        stackName = `${slugify(block.brandName)}-rcs-demo`;
      }
    }
    if (!stackName) {
      out(`${id}: kept (cannot tell which stack it belongs to).\n`);
      continue;
    }
    const st = await stackStatus(execFile, stackName, entryRegion, profileArgs, childEnv);
    if (st.status === 'missing') {
      removed.push(id);
      out(`${id}: stack ${stackName} not found in ${entryRegion}; removed.\n`);
    } else if (st.status === 'present') {
      out(`${id}: stack ${stackName} exists in ${entryRegion}; kept.\n`);
    } else {
      out(`${id}: kept (could not check stack ${stackName}: ${st.reason}).\n`);
    }
  }
  if (removed.length > 0) {
    const result = removeFromStore(existing.text, removed);
    const writeError = writeStoreText(root, result.text);
    if (writeError) {
      err(writeError);
      return 1;
    }
    out('Reload the dashboard.\n');
  }
  return 0;
}

/**
 * The CLI. Dependencies are injectable so checks can run it with a fake
 * `execFile` and a temporary repository root; it makes no AWS call itself.
 *
 * @returns {Promise<number>} the exit status
 */
export async function main(
  argv,
  {
    execFile = nodeExecFile,
    root = process.cwd(),
    env = process.env,
    out = (s) => process.stdout.write(s),
    err = (s) => process.stderr.write(s),
    now = () => new Date(),
  } = {},
) {
  const usage = 'usage: node scripts/wire-dashboard-brand.mjs <Brand_Id> <REGION> [<PROFILE>]\n';
  if (argv[0] === '--remove') return removeMain(argv.slice(1), { root, out, err });
  if (argv[0] === '--prune') return pruneMain(argv.slice(1), { execFile, root, env, out, err });
  const [brandId, region, profile, ...extra] = argv;

  // 1. Validate everything before any AWS call.
  if (!existsSync(join(root, 'content', 'brand.md')) || !existsSync(join(root, 'cdk', 'package.json'))) {
    err('Run this command from the repository root (content/brand.md and cdk/package.json not found).\n');
    return 2;
  }
  if (extra.length > 0 || brandId === undefined) {
    err(usage);
    return 2;
  }
  const catalog = readCatalog(root);
  if (catalog.error) {
    err(`Cannot read the brand catalog: ${catalog.error}.\n`);
    return 2;
  }
  const validIds = Object.keys(catalog.brands).filter(isValidBrandId);
  if (!isValidBrandId(brandId) || !validIds.includes(brandId)) {
    err(
      `Unknown Brand_Id ${JSON.stringify(brandId)}. Valid ids: ` +
        `${validIds.length ? validIds.join(', ') : '(none defined)'}.\n`,
    );
    return 2;
  }
  if (typeof region !== 'string' || !/^[a-z0-9-]+$/.test(region)) {
    err(`Invalid REGION ${JSON.stringify(region ?? '')}: expected a Region such as us-east-1.\n`);
    return 2;
  }
  if (profile !== undefined && profile === '') {
    err('Invalid PROFILE "": omit it or name an AWS profile.\n');
    return 2;
  }
  const block = catalog.brands[brandId];
  if (!isPlainObject(block) || typeof block.brandName !== 'string' || !block.brandName.trim()) {
    err(`brands.${brandId}.brandName is missing in content/brand.md.\n`);
    return 2;
  }

  // 2. Stack name, exactly as the CDK derives it.
  const stackName = `${slugify(block.brandName)}-rcs-demo`;
  const profileArgs = profile !== undefined ? ['--profile', profile] : [];
  const childEnv = { ...env, AWS_PAGER: '' };

  // 3. Stack outputs.
  const stack = await run(
    execFile,
    ['cloudformation', 'describe-stacks', '--stack-name', stackName, '--region', region,
      ...profileArgs, '--query', 'Stacks[0].Outputs', '--output', 'json'],
    childEnv,
  );
  if (!stack.ok) {
    err(`Could not read stack ${stackName} in ${region}: ${stack.category}\n`);
    return 1;
  }
  let outputs;
  try {
    outputs = JSON.parse(stack.stdout);
  } catch {
    err(`Could not read stack ${stackName} in ${region}: unexpected output\n`);
    return 1;
  }
  const output = (k) => {
    const o = Array.isArray(outputs) ? outputs.find((x) => x && x.OutputKey === k) : undefined;
    return o && typeof o.OutputValue === 'string' ? o.OutputValue.trim() : '';
  };
  const apiUrl = output('ApiUrl');
  const secretName = output('ApiKeySecretName');
  if (!apiUrl || !secretName) {
    err(`Could not read stack ${stackName} in ${region}: missing output ${!apiUrl ? 'ApiUrl' : 'ApiKeySecretName'}\n`);
    return 1;
  }

  // 4. The key: only ever this child's stdout buffer.
  const secret = await run(
    execFile,
    ['secretsmanager', 'get-secret-value', '--secret-id', secretName, '--region', region,
      ...profileArgs, '--query', 'SecretString', '--output', 'text'],
    childEnv,
  );
  if (!secret.ok) {
    err(`Could not read secret ${secretName}: ${secret.category}\n`);
    return 1;
  }
  const apiKey = secret.stdout.replace(/\r?\n$/, '');
  if (!apiKey || apiKey === 'None') {
    err(`Could not read secret ${secretName}: empty value\n`);
    return 1;
  }

  // 5. Merge into the store; never overwrite content we could not read.
  const existing = readStoreText(root);
  if (existing.error) {
    err(existing.error);
    return 1;
  }
  let text;
  try {
    // Where the stack lives, so `--prune` later checks the right place.
    text = mergeStore(existing.text, brandId, apiUrl, apiKey, now(), { region, stackName });
  } catch (e) {
    const reason = e instanceof StoreError ? e.reason : 'unexpected structure';
    err(`Existing ${STORE_REL} is unreadable (${reason}); fix or delete it.\n`);
    return 1;
  }

  // 6. Atomic write.
  const writeError = writeStoreText(root, text);
  if (writeError) {
    err(writeError);
    return 1;
  }

  // 7. Confirm, naming the id and URL only.
  out(`Wired ${brandId}: ${apiUrl} -> ${STORE_REL}. Reload the dashboard to see it in the brand picker.\n`);
  return 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2)).then(
    (code) => { process.exitCode = code; },
    (e) => {
      // Never print the error message: it is not ours to vouch for.
      process.stderr.write(`Unexpected error (${e?.code ?? e?.name ?? 'error'}).\n`);
      process.exitCode = 1;
    },
  );
}
