/**
 * Brand-connections dev-server endpoint (dashboard brand picker, design C1).
 *
 * A Vite plugin that serves `GET /__rcs-demo/brand-connections` from the dev
 * server only (`apply: 'serve'`, `configureServer`, no preview server). The
 * response lists the per-brand (API URL, API key) pairs found in the
 * Connection_Store (`.deploy/dashboard-brands.json`, written by
 * `scripts/wire-dashboard-brand.mjs`) and in the Legacy_Brand_Env_Files
 * (`web/.env.<Brand_Id>`). The browser resolves precedence; this file only
 * reads, validates and serves the raw per-source entries.
 *
 * The response carries API keys, so the endpoint is gated and fails closed:
 * it answers only a same-origin GET from a loopback client address with a
 * loopback `Host` header and the marker header, even when Vite was started
 * with `--host`. Every other request gets a body with no connection data, and
 * the gate runs before any file is read.
 *
 * Plain ESM with JSDoc types (like scripts/version.mjs) so Node can import it
 * directly. It sits outside web/src, so it is never part of the client bundle.
 *
 * Nothing here logs or echoes file contents: failures are reported with a
 * closed set of reasons, never a JSON.parse message (Node's SyntaxError text
 * quotes a slice of the input, which could include a key).
 */
import { closeSync, constants as fsConstants, fstatSync, openSync, readSync, readdirSync } from 'node:fs';
import { isIPv4 } from 'node:net';
import { dirname, join, relative, sep } from 'node:path';

/** The endpoint path. The dashboard fetches exactly this, with the marker header. */
export const CONNECTIONS_PATH = '/__rcs-demo/brand-connections';

/**
 * Marker header (lowercase, as Node exposes request headers). Its value must be
 * exactly "1". A cross-origin fetch that sets a custom header needs a CORS
 * preflight, which nothing answers (the endpoint refuses OPTIONS with 405 and
 * sends no Access-Control-* header).
 */
export const MARKER_HEADER = 'x-rcs-demo-connections';

/** Files larger than this are skipped as "too large". */
const MAX_FILE_BYTES = 64 * 1024;

/** Vite's reserved mode names, plus the committed `.env.example` template. */
const RESERVED_ENV_SUFFIXES = new Set(['local', 'development', 'production', 'test', 'example']);

/** Hostnames accepted in the `Host` header (after lowercasing and port removal). */
const LOOPBACK_HOSTNAMES = new Set(['localhost', '127.0.0.1', '[::1]']);

/** `server.host` values that keep the dev server bound to this machine only. */
const LOOPBACK_BIND_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '[::1]']);

const LOG_PREFIX = '[brand-connections]';

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

/**
 * A valid Brand_Id: lowercase ASCII letters, digits and hyphens, starting with
 * a letter, at most 32 characters.
 * @param {unknown} s
 * @returns {boolean}
 */
export function isValidBrandId(s) {
  return typeof s === 'string' && /^[a-z][a-z0-9-]{0,31}$/.test(s);
}

/**
 * The Brand_Id of a Legacy_Brand_Env_File name, or null when the name is not
 * one. Accepted: `.env.<suffix>` where the suffix contains no dot (so
 * `.env.anytravel.local` and `.env.old-stack.bak` are excluded), passes
 * isValidBrandId, and is not a Vite reserved mode name (`local`,
 * `development`, `production`, `test`) or the `example` template.
 * @param {unknown} name
 * @returns {string | null}
 */
export function legacyEnvFileBrandId(name) {
  if (typeof name !== 'string') return null;
  const m = /^\.env\.([^.]+)$/.exec(name);
  if (!m) return null;
  const suffix = m[1];
  if (!isValidBrandId(suffix) || RESERVED_ENV_SUFFIXES.has(suffix)) return null;
  return suffix;
}

/**
 * Parse dotenv-style text: `KEY=VALUE` lines with an optional `export ` prefix,
 * `#` comment lines, and single-, double- or backtick-quoted values with the
 * quotes stripped. An unquoted value ends at the first `#` (as dotenv, which
 * Vite uses, reads it). Values are not interpolated. The last assignment of a
 * key wins. The result has a null prototype.
 * @param {string} text
 * @returns {Record<string, string>}
 */
export function parseEnvFile(text) {
  /** @type {Record<string, string>} */
  const out = Object.create(null);
  if (typeof text !== 'string') return out;
  const body = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  for (const rawLine of body.split(/\r\n|\n|\r/)) {
    let line = rawLine.trim();
    if (line === '' || line.startsWith('#')) continue;
    if (/^export\s+/.test(line)) line = line.replace(/^export\s+/, '');
    const eq = line.indexOf('=');
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    if (!/^[A-Za-z_][A-Za-z0-9_.-]*$/.test(key)) continue;
    let value = line.slice(eq + 1).trim();
    const q = value[0];
    if ((q === '"' || q === "'" || q === '`') && value.length >= 2 && value.indexOf(q, 1) > 0) {
      value = value.slice(1, value.indexOf(q, 1));
    } else {
      const hash = value.indexOf('#');
      if (hash >= 0) value = value.slice(0, hash);
      value = value.trim();
    }
    out[key] = value;
  }
  return out;
}

/**
 * True for a loopback client address: IPv4 127.0.0.0/8, IPv6 `::1`, or an
 * IPv4-mapped `::ffff:127.x.x.x`.
 * @param {unknown} addr
 * @returns {boolean}
 */
export function isLoopbackAddress(addr) {
  if (typeof addr !== 'string' || addr === '') return false;
  const a = addr.toLowerCase();
  if (a === '::1') return true;
  const v4 = a.startsWith('::ffff:') ? a.slice('::ffff:'.length) : a;
  return isIPv4(v4) && v4.split('.')[0] === '127';
}

/**
 * Split a `Host`-style value into a lowercased hostname and an optional port.
 * Returns null when the value is malformed.
 * @param {string} value
 * @returns {{ hostname: string, port: string | null } | null}
 */
function splitHostPort(value) {
  const v = value.toLowerCase();
  const m = /^(\[[^\]]*\]|[^:[\]]+)(?::(\d{1,5}))?$/.exec(v);
  if (!m) return null;
  return { hostname: m[1], port: m[2] ?? null };
}

/**
 * True when the `Host` header names a loopback host: exactly `localhost`,
 * `127.0.0.1` or `[::1]` (case-insensitive), with an optional numeric port. A
 * missing header, a trailing-dot form or any other name is false. This is the
 * DNS-rebinding defense: a page on another name that resolves to 127.0.0.1
 * still sends its own name.
 * @param {unknown} host
 * @returns {boolean}
 */
export function isLoopbackHostHeader(host) {
  if (typeof host !== 'string' || host === '') return false;
  const hp = splitHostPort(host);
  return hp !== null && LOOPBACK_HOSTNAMES.has(hp.hostname);
}

/**
 * First value of a header that Node may have exposed as a string or an array.
 * @param {unknown} v
 * @returns {string | undefined}
 */
function headerValue(v) {
  if (Array.isArray(v)) return v.length === 1 && typeof v[0] === 'string' ? v[0] : '\u0000invalid';
  return typeof v === 'string' ? v : undefined;
}

/**
 * True when `origin` is an http(s) origin on a loopback host whose host and
 * port equal the `Host` header.
 * @param {string} origin
 * @param {string} host
 * @returns {boolean}
 */
function originMatchesHost(origin, host) {
  let u;
  try {
    u = new URL(origin);
  } catch {
    return false;
  }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') return false;
  if (u.origin.toLowerCase() !== origin.toLowerCase().replace(/\/$/, '')) return false;
  if (!LOOPBACK_HOSTNAMES.has(u.hostname.toLowerCase())) return false;
  return u.host.toLowerCase() === host.toLowerCase();
}

/**
 * The request gate. Fails closed: every check must pass.
 *
 * 1. method is GET (otherwise 405);
 * 2. the client address is loopback;
 * 3. the `Host` header names a loopback host;
 * 4. `Sec-Fetch-Site` is absent or exactly `same-origin`;
 * 5. `Origin` is absent or a loopback origin whose host:port equals `Host`;
 * 6. the marker header is exactly `1`.
 *
 * @param {{ method?: unknown, remoteAddress?: unknown, headers?: Record<string, unknown> }} reqLike
 * @returns {{ ok: true } | { ok: false, status: 403 | 405 }}
 */
export function gate(reqLike) {
  const r = reqLike && typeof reqLike === 'object' ? reqLike : {};
  if (r.method !== 'GET') return { ok: false, status: 405 };
  const headers = r.headers && typeof r.headers === 'object' ? r.headers : {};
  const deny = /** @type {const} */ ({ ok: false, status: 403 });

  if (!isLoopbackAddress(r.remoteAddress)) return deny;

  const host = headerValue(headers.host);
  if (host === undefined || !isLoopbackHostHeader(host)) return deny;

  const site = headerValue(headers['sec-fetch-site']);
  if (site !== undefined && site !== 'same-origin') return deny;

  const origin = headerValue(headers.origin);
  if (origin !== undefined && !originMatchesHost(origin, host)) return deny;

  if (headerValue(headers[MARKER_HEADER]) !== '1') return deny;

  return { ok: true };
}

// ---------------------------------------------------------------------------
// File reading (closed-set failure reasons only)
// ---------------------------------------------------------------------------

/**
 * Closed-set reason for an fs error: the errno code only, never the message.
 * @param {unknown} err
 * @returns {string}
 */
function readFailureReason(err) {
  const code = err && typeof err === 'object' && 'code' in err ? /** @type {any} */ (err).code : undefined;
  const safe = typeof code === 'string' && /^E[A-Z0-9]{1,15}$/.test(code) ? code : 'UNKNOWN';
  return `could not be read (${safe})`;
}

/**
 * Read a small regular file as UTF-8 text without blocking on a FIFO and
 * without reading more than the size limit.
 * @param {string} path
 * @returns {{ ok: true, text: string } | { ok: false, absent: boolean, reason: string }}
 */
function readSmallFile(path) {
  let fd;
  try {
    // O_NONBLOCK so opening a FIFO does not hang the dev server (0 on Windows).
    fd = openSync(path, fsConstants.O_RDONLY | (fsConstants.O_NONBLOCK ?? 0));
  } catch (err) {
    const code = err && typeof err === 'object' ? /** @type {any} */ (err).code : undefined;
    return { ok: false, absent: code === 'ENOENT', reason: readFailureReason(err) };
  }
  try {
    const st = fstatSync(fd);
    if (st.isDirectory()) return { ok: false, absent: false, reason: 'could not be read (EISDIR)' };
    if (!st.isFile()) return { ok: false, absent: false, reason: 'could not be read (EINVAL)' };
    if (st.size > MAX_FILE_BYTES) return { ok: false, absent: false, reason: 'too large' };
    // Read up to one byte past the limit, in case the file grew after fstat.
    const buf = Buffer.alloc(MAX_FILE_BYTES + 1);
    let total = 0;
    for (;;) {
      const n = readSync(fd, buf, total, buf.length - total, null);
      if (n === 0) break;
      total += n;
      if (total > MAX_FILE_BYTES) return { ok: false, absent: false, reason: 'too large' };
    }
    return { ok: true, text: buf.subarray(0, total).toString('utf8') };
  } catch (err) {
    return { ok: false, absent: false, reason: readFailureReason(err) };
  } finally {
    try {
      closeSync(fd);
    } catch {
      /* ignore */
    }
  }
}

/**
 * @param {unknown} v
 * @returns {v is Record<string, unknown>}
 */
function isPlainObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

/**
 * @typedef {{ source: 'store' | 'envFile', brandId: string, apiUrl: string, apiKey: string, file: string }} SourceEntry
 */

/**
 * Read the Connection_Store. `absent` (no file) carries no reason; `unreadable`
 * carries one closed-set reason: `could not be read (<ERRNO>)`, `not valid
 * JSON`, `unexpected structure` or `too large`. Entries whose key is not a
 * valid Brand_Id, or whose value is not an object, are skipped. A non-string
 * `apiUrl` or `apiKey` reads as "".
 * @param {string} path absolute path of the store
 * @param {string} [file] display name (repo-relative) used in the entries
 * @returns {{ status: 'absent' | 'ok' | 'unreadable', reason?: string, entries: SourceEntry[] }}
 */
export function readStore(path, file = '.deploy/dashboard-brands.json') {
  const r = readSmallFile(path);
  if (!r.ok) {
    return r.absent ? { status: 'absent', entries: [] } : { status: 'unreadable', reason: r.reason, entries: [] };
  }
  const text = r.text.charCodeAt(0) === 0xfeff ? r.text.slice(1) : r.text;
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    // Never forward the SyntaxError message: it quotes the input.
    return { status: 'unreadable', reason: 'not valid JSON', entries: [] };
  }
  if (!isPlainObject(data) || !isPlainObject(data.brands)) {
    return { status: 'unreadable', reason: 'unexpected structure', entries: [] };
  }
  /** @type {SourceEntry[]} */
  const entries = [];
  for (const brandId of Object.keys(data.brands).sort()) {
    if (!isValidBrandId(brandId)) continue;
    const e = data.brands[brandId];
    if (!isPlainObject(e)) continue;
    entries.push({
      source: 'store',
      brandId,
      apiUrl: typeof e.apiUrl === 'string' ? e.apiUrl.trim() : '',
      apiKey: typeof e.apiKey === 'string' ? e.apiKey.trim() : '',
      file,
    });
  }
  return { status: 'ok', entries };
}

/**
 * Read every Legacy_Brand_Env_File in `dir`. Files that fail
 * legacyEnvFileBrandId are not considered at all. Unreadable or oversized
 * files are skipped and reported in `problems` with a closed-set reason.
 * @param {string} dir absolute path of the env directory (web/)
 * @param {string} [displayDir] repo-relative display prefix for file names
 * @returns {{ entries: SourceEntry[], problems: { file: string, reason: string }[] }}
 */
export function readEnvFiles(dir, displayDir = 'web') {
  /** @type {SourceEntry[]} */
  const entries = [];
  /** @type {{ file: string, reason: string }[]} */
  const problems = [];
  const label = (/** @type {string} */ name) => (displayDir ? `${displayDir}/${name}` : name);
  let names;
  try {
    names = readdirSync(dir);
  } catch (err) {
    problems.push({ file: displayDir || '.', reason: readFailureReason(err) });
    return { entries, problems };
  }
  for (const name of names.sort()) {
    const brandId = legacyEnvFileBrandId(name);
    if (brandId === null) continue;
    const file = label(name);
    const r = readSmallFile(join(dir, name));
    if (!r.ok) {
      if (!r.absent) problems.push({ file, reason: r.reason });
      continue;
    }
    const env = parseEnvFile(r.text);
    entries.push({
      source: 'envFile',
      brandId,
      apiUrl: (env.VITE_API_URL ?? '').trim(),
      apiKey: (env.VITE_API_KEY ?? '').trim(),
      file,
    });
  }
  return { entries, problems };
}

// ---------------------------------------------------------------------------
// The plugin
// ---------------------------------------------------------------------------

/**
 * Write a JSON response with the security headers and no Access-Control-*
 * header, whatever an earlier middleware may have set.
 * @param {import('node:http').ServerResponse} res
 * @param {number} status
 * @param {unknown} body
 * @param {Record<string, string>} [extra]
 */
function sendJson(res, status, body, extra = {}) {
  for (const name of res.getHeaderNames()) {
    if (name.toLowerCase().startsWith('access-control-')) res.removeHeader(name);
  }
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('Cross-Origin-Resource-Policy', 'same-origin');
  for (const [k, v] of Object.entries(extra)) res.setHeader(k, v);
  res.end(JSON.stringify(body));
}

/**
 * Repo-relative, forward-slash display path.
 * @param {string} root
 * @param {string} p
 */
function displayPath(root, p) {
  const rel = relative(root, p);
  return (rel === '' ? '.' : rel).split(sep).join('/');
}

/**
 * The brand-connections Vite plugin. Dev server only: `apply: 'serve'` and a
 * `configureServer` hook; there is deliberately no `configurePreviewServer`.
 *
 * @param {{ storePath: string, envDir: string, rootDir?: string }} options
 *   storePath: absolute path of `.deploy/dashboard-brands.json`;
 *   envDir: absolute path of `web/`;
 *   rootDir: repository root for display names (default: the parent of envDir).
 * @returns {import('vite').Plugin}
 */
export function brandConnections({ storePath, envDir, rootDir }) {
  const root = rootDir ?? dirname(envDir);
  const storeFile = displayPath(root, storePath);
  const envDisplayDir = displayPath(root, envDir);
  /** (file, reason) pairs already logged, so each is logged once. */
  const logged = new Set();

  return {
    name: 'rcs-demo-brand-connections',
    apply: 'serve',
    configureServer(server) {
      const logger = server.config.logger;
      /** @param {string} file @param {string} reason */
      const warnOnce = (file, reason) => {
        const k = `${file}\u0000${reason}`;
        if (logged.has(k)) return;
        logged.add(k);
        // File name and closed-set reason only; never contents or a key.
        logger.warn(`${LOG_PREFIX} ${file}: ${reason}; ignored`);
      };

      const host = server.config.server.host;
      const loopbackBind = host === undefined || (typeof host === 'string' && LOOPBACK_BIND_HOSTS.has(host.toLowerCase()));
      if (!loopbackBind) {
        logger.warn(
          `${LOG_PREFIX} the dashboard is reachable from other machines; brand connections are still served only to this machine`,
        );
      }

      // Registered directly (not in a returned post-hook), so it runs before
      // Vite's own CORS, host-check and static middlewares. It finishes every
      // response under its path itself and never calls next().
      server.middlewares.use(CONNECTIONS_PATH, (req, res) => {
        try {
          const verdict = gate({ method: req.method, remoteAddress: req.socket?.remoteAddress, headers: req.headers });
          if (!verdict.ok) {
            if (verdict.status === 405) {
              sendJson(res, 405, { error: 'method not allowed' }, { Allow: 'GET' });
            } else {
              sendJson(res, 403, { error: 'forbidden' });
            }
            return;
          }
          // Connect strips the mount path: the exact endpoint is "/" or "/?…".
          const rest = req.url ?? '/';
          if (rest !== '/' && !rest.startsWith('/?')) {
            sendJson(res, 404, { error: 'not found' });
            return;
          }

          // Re-read on every request so a newly wired brand shows after a reload.
          const store = readStore(storePath, storeFile);
          if (store.status === 'unreadable' && store.reason) warnOnce(storeFile, store.reason);
          const env = readEnvFiles(envDir, envDisplayDir);
          for (const p of env.problems) warnOnce(p.file, p.reason);

          /** @type {{ status: string, file: string, entries: SourceEntry[], reason?: string }} */
          const storeBody = { status: store.status, file: storeFile, entries: store.entries };
          if (store.reason) storeBody.reason = store.reason;
          sendJson(res, 200, { version: 1, store: storeBody, envFiles: env.entries });
        } catch {
          if (res.headersSent) {
            res.end();
          } else {
            sendJson(res, 500, { error: 'internal' });
          }
        }
      });
    },
  };
}
