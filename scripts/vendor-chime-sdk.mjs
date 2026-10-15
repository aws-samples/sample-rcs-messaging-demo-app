#!/usr/bin/env node
/**
 * Bundle amazon-chime-sdk-js into a browser ES module for the RCS webview.
 *
 * Why this exists: amazon-chime-sdk-js is distributed as CommonJS, so a
 * <script type="module"> in lambda/webviews/video-visit.html cannot import it
 * directly. This script bundles the five exports the webview uses into a browser
 * ES module. The dashboard doesn't need this — Vite bundles the same package for
 * the web UI — but the webview is a single static HTML file served by Lambda,
 * with no build step of its own.
 *
 * The alternative was a CDN, which is what the webview originally did (jsDelivr's
 * /+esm build). That is wrong for a published sample twice over: it hands a third
 * party the ability to run code in a page that asks for the user's camera, and it
 * makes the demo break when a CDN is unreachable. The output is committed to the
 * repo so `cdk deploy` works from a fresh clone with no extra steps.
 *
 * Run after changing the pinned SDK version in web/package.json, then commit the
 * result:
 *
 *     node scripts/vendor-chime-sdk.mjs
 *
 * The version is read from web/node_modules rather than named here, so the
 * webview and the dashboard cannot drift onto different SDK versions.
 *
 * Licensing: the bundle is not all Amazon code. Besides amazon-chime-sdk-js
 * (Apache-2.0) it contains the third-party npm packages the SDK depends on, under
 * MIT, BSD, Zlib and other licenses, and those licenses require their copyright
 * and permission notices to travel with copies. Minification strips comments,
 * and only two of the bundled packages (long, tslib) carry a comment esbuild
 * treats as a legal comment, so the script asks esbuild for a metafile, finds
 * the packages that actually contribute bytes to the output, and writes
 * lambda/webviews/chime-sdk.LICENSES.txt next to the bundle from the license
 * files each package ships. The text is copied, never written by hand, so the
 * notices follow the dependency versions.
 */
import { readFileSync, writeFileSync, existsSync, rmSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, join, relative } from 'node:path';
import { createRequire } from 'node:module';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

// esbuild comes from web/node_modules (it is already there as a Vite dependency,
// so this adds nothing to install). Resolved explicitly rather than imported by
// name because a bare ESM import resolves relative to this file in scripts/,
// where there is no node_modules at all.
const webRequire = createRequire(join(root, 'web', 'package.json'));
let build;
try {
  ({ build } = await import(pathToFileURL(webRequire.resolve('esbuild'))));
} catch {
  console.error("error: esbuild not found. Run 'npm ci' in web/ first.");
  process.exit(1);
}
const pkgDir = join(root, 'web', 'node_modules', 'amazon-chime-sdk-js');
const out = join(root, 'lambda', 'webviews', 'chime-sdk.js');

if (!existsSync(pkgDir)) {
  console.error(`error: ${pkgDir} not found. Run 'npm ci' in web/ first.`);
  process.exit(1);
}
const version = JSON.parse(readFileSync(join(pkgDir, 'package.json'), 'utf8')).version;
console.log(`Bundling amazon-chime-sdk-js@${version} for the webview…`);

/**
 * The SDK depends on @aws-sdk/@smithy packages for its messaging features, and
 * those `require()` Node builtins — node:http, node:child_process, fs, and so on
 * — from credential-provider code paths. They are part of the bundle graph, so
 * the browser build needs something to resolve them to.
 *
 * Stubbing them is sound rather than a fudge: the webview passes Meeting and
 * Attendee objects it was handed by the backend and never constructs an AWS
 * client, so nothing in the meeting path reads credentials from a filesystem,
 * an IMDS endpoint, or a subprocess.
 *
 * The stub is permissive on property *access* and throws only when something is
 * actually called or constructed. That asymmetry is required, not stylistic:
 * several of these packages destructure at module scope
 * (`const { Readable } = require('node:stream')`), which runs on load. A stub
 * that threw on access would take the whole bundle down at import time, which is
 * exactly what the first version of this script did. Throwing on *use* keeps the
 * dead code dead while still failing with a readable sentence if a future change
 * genuinely reaches one of these paths.
 */
const nodeBuiltinStub = {
  name: 'node-builtin-stub',
  setup(b) {
    const builtins = new RegExp(
      '^(node:)?(assert|async_hooks|buffer|child_process|cluster|console|constants|crypto'
      + '|dgram|dns|domain|events|fs|http|http2|https|inspector|module|net|os|path|perf_hooks'
      + '|process|punycode|querystring|readline|repl|stream|string_decoder|sys|timers|tls'
      + '|trace_events|tty|url|util|v8|vm|worker_threads|zlib)(/.*)?$'
    );
    b.onResolve({ filter: builtins }, (args) => ({ path: args.path, namespace: 'node-stub' }));
    b.onLoad({ filter: /.*/, namespace: 'node-stub' }, (args) => ({
      contents: `
const MODULE = ${JSON.stringify(args.path)};
function reject(name) {
  throw new Error(
    'amazon-chime-sdk-js reached ' + MODULE + '.' + name + ', a Node built-in stubbed out of '
    + 'the browser bundle. The RCS webview never constructs an AWS client, so no '
    + 'credential-provider or filesystem path should run. See scripts/vendor-chime-sdk.mjs.');
}
// Returns something that can be held, destructured, subclassed and inspected,
// and complains only when called or constructed.
function stub(name) {
  const f = function () { reject(name); };
  return new Proxy(f, {
    apply: () => reject(name),
    construct: () => reject(name),
    get(target, prop) {
      if (typeof prop === 'symbol' || prop === 'prototype' || prop in target) return target[prop];
      if (prop === '__esModule') return false;
      return stub(name + '.' + String(prop));
    },
  });
}
module.exports = new Proxy({}, {
  get(_t, prop) {
    if (typeof prop === 'symbol') return undefined;
    if (prop === '__esModule') return false;
    return stub(String(prop));
  },
});
`,
      loader: 'js',
    }));
  },
};

// Only the five exports the webview uses. The entry lives inside web/ because
// esbuild resolves bare specifiers relative to the entry point, and from
// anywhere else it cannot see web/node_modules.
const entry = join(root, 'web', '.chime-vendor-entry.js');
writeFileSync(entry, [
  "export {",
  "  ConsoleLogger,",
  "  LogLevel,",
  "  DefaultDeviceController,",
  "  MeetingSessionConfiguration,",
  "  DefaultMeetingSession,",
  "} from 'amazon-chime-sdk-js';",
].join('\n'));

let result;
try {
  result = await build({
    entryPoints: [entry],
    outfile: out,
    // Paths in the metafile are relative to this directory.
    absWorkingDir: root,
    metafile: true,
    bundle: true,
    format: 'esm',
    platform: 'browser',
    target: 'es2020',
    minify: true,
    // Keeping legal comments would cover only two packages (long, tslib), so
    // the notices come from the package license files instead (see below).
    legalComments: 'none',
    // `global` is Node's, and the SDK reads it at load time; this maps it to
    // globalThis so the page does not stop with "ReferenceError: global is not
    // defined" before any of our code runs. web/vite.config.ts uses the same shim
    // for the same reason.
    define: { global: 'globalThis', 'process.env.NODE_ENV': '"production"' },
    plugins: [nodeBuiltinStub],
    logLevel: 'warning',
  });
} finally {
  rmSync(entry, { force: true });
}

// ── Third-party license notices ──────────────────────────────────────────────
//
// The metafile lists every input file and how many bytes of it reached the
// output. Group the inputs that contribute bytes by npm package: the package
// directory is whatever follows the *last* `node_modules/` in the path (nested
// installs are possible), plus the scope for `@scope/name`. Inputs that are not
// in a package are the generated entry file and the node-builtin stub above,
// which are this repository's own code; anything else means the build changed
// shape and the notices below can no longer be trusted, so stop.
const licensesOut = join(root, 'lambda', 'webviews', 'chime-sdk.LICENSES.txt');
const outputs = Object.values(result.metafile.outputs);
if (outputs.length !== 1) {
  console.error(`error: expected one esbuild output, got ${outputs.length}.`);
  process.exit(1);
}

function packageDirOf(inputPath) {
  const marker = 'node_modules/';
  const at = inputPath.lastIndexOf(marker);
  if (at === -1) return null;
  const parts = inputPath.slice(at + marker.length).split('/');
  const nameParts = parts[0].startsWith('@') ? 2 : 1;
  if (parts.length <= nameParts) return null;
  return inputPath.slice(0, at + marker.length) + parts.slice(0, nameParts).join('/');
}

const entryInput = relative(root, entry).split('\\').join('/');
const packageDirs = new Set();
const unexpected = [];
for (const [file, info] of Object.entries(outputs[0].inputs)) {
  if (info.bytesInOutput <= 0) continue;
  const dir = packageDirOf(file);
  if (dir) packageDirs.add(dir);
  else if (!file.startsWith('node-stub:') && file !== entryInput) unexpected.push(file);
}
if (unexpected.length) {
  console.error(`error: bundle includes code that is not from an npm package: ${unexpected.join(', ')}`);
  process.exit(1);
}

// License text is copied byte for byte from the package, apart from line endings
// and trailing blank lines, so the file is the same on every platform.
const LICENSE_FILE = /^(licen[cs]e|copying|notice)/i;
const readText = (file) => readFileSync(file, 'utf8').replace(/\r\n?/g, '\n').trimEnd();

// pako is "MIT AND Zlib", but its LICENSE file is the MIT half only. The Zlib half
// is the header comment of the ported zlib sources, so take it from there.
const EXTRA_NOTICE_SOURCES = { pako: 'lib/zlib/deflate.js' };

function headerCommentOf(file) {
  const lines = readText(file).split('\n');
  const first = lines.findIndex((l) => l.startsWith('//'));
  if (first === -1) return '';
  const block = [];
  for (let i = first; i < lines.length && lines[i].startsWith('//'); i++) {
    block.push(lines[i].replace(/^\/\/ ?/, ''));
  }
  return block.join('\n');
}

function spdxOf(json) {
  if (typeof json.license === 'string') return json.license;
  if (json.license && typeof json.license.type === 'string') return json.license.type;
  if (Array.isArray(json.licenses)) {
    return json.licenses.map((l) => l && l.type).filter(Boolean).join(' OR ') || null;
  }
  return null;
}

function repositoryOf(json) {
  let r = json.repository;
  if (r && typeof r === 'object') r = r.url;
  if (typeof r !== 'string' || !r) return typeof json.homepage === 'string' ? json.homepage : null;
  r = r.replace(/^git\+/, '').replace(/^git:\/\//, 'https://')
    .replace(/^ssh:\/\/git@/, 'https://').replace(/^git@([\w.-]+):/, 'https://$1/')
    .replace(/\.git$/, '');
  const shorthand = /^(?:github:)?([\w.-]+\/[\w.-]+)$/.exec(r);
  return shorthand ? `https://github.com/${shorthand[1]}` : r;
}

function authorOf(json) {
  const a = json.author;
  if (typeof a === 'string') return a;
  if (a && typeof a === 'object' && a.name) return a.url ? `${a.name} (${a.url})` : a.name;
  return null;
}

const byId = new Map();
for (const dir of [...packageDirs].sort()) {
  const abs = join(root, dir);
  const json = JSON.parse(readFileSync(join(abs, 'package.json'), 'utf8'));
  const id = `${json.name}@${json.version}`;
  if (byId.has(id)) continue; // same release installed twice: one notice is enough
  const files = readdirSync(abs)
    .filter((f) => LICENSE_FILE.test(f) && statSync(join(abs, f)).isFile())
    .sort()
    .map((f) => ({ name: f, text: readText(join(abs, f)) }));
  const extra = EXTRA_NOTICE_SOURCES[json.name];
  if (extra) {
    const text = existsSync(join(abs, extra)) ? headerCommentOf(join(abs, extra)) : '';
    if (!text) {
      console.error(`error: expected a license header comment in ${json.name}/${extra}; update EXTRA_NOTICE_SOURCES.`);
      process.exit(1);
    }
    files.push({ name: `header comment of ${extra}`, text });
  }
  byId.set(id, {
    id, name: json.name, version: json.version, files,
    spdx: spdxOf(json), repo: repositoryOf(json), author: authorOf(json),
  });
}

const sdk = byId.get(`amazon-chime-sdk-js@${version}`);
if (!sdk || !sdk.files.some((f) => /^licen[cs]e/i.test(f.name))) {
  console.error('error: amazon-chime-sdk-js is missing from the bundle inputs or ships no LICENSE file.');
  process.exit(1);
}
const others = [...byId.values()].filter((p) => p !== sdk)
  .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));

const noNotice = others.concat(sdk).filter((p) => p.files.length === 0);
if (noNotice.some((p) => !p.spdx)) {
  const names = noNotice.filter((p) => !p.spdx).map((p) => p.id).join(', ');
  console.error(`error: no license file and no license field in package.json for: ${names}`);
  process.exit(1);
}
for (const p of noNotice) {
  console.warn(`warning: ${p.id} ships no license file; the notices file records its package.json fields only.`);
}

// The banner names the licenses that were actually found, so it cannot go stale.
const thirdPartyIds = [...new Set(others.flatMap((p) => (p.spdx || '').split(/[\s()]+/))
  .filter((t) => t && !['AND', 'OR', 'WITH'].includes(t.toUpperCase())))]
  .sort();
const idList = thirdPartyIds.length > 1
  ? `${thirdPartyIds.slice(0, -1).join(', ')} and ${thirdPartyIds[thirdPartyIds.length - 1]}`
  : thirdPartyIds.join('');

const RULE = '='.repeat(78);

// Many @aws-sdk and @smithy packages ship the same Apache-2.0 text, so a
// text that is byte-identical to one already printed is referenced, not repeated.
// Anything that differs even by a copyright line is printed in full.
const printed = new Map();

function section(p) {
  const lines = [
    RULE,
    p.id,
    RULE,
    `SPDX license: ${p.spdx || '(not declared in package.json)'}`,
    `Repository: ${p.repo || '(not declared in package.json)'}`,
    '',
  ];
  if (p.files.length === 0) {
    lines.push('This package ships no license file. Recorded from its package.json:');
    lines.push(`  Author: ${p.author || '(not declared)'}`);
    if (p.spdx === 'Apache-2.0') {
      lines.push('The Apache License 2.0 text is reproduced in Part 1.');
    }
    lines.push('');
  }
  for (const f of p.files) {
    const first = printed.get(f.text);
    if (first) {
      lines.push(`--- ${f.name}: identical to the ${first} ---`, '');
    } else {
      printed.set(f.text, `${f.name} of ${p.id}`);
      lines.push(`--- ${f.name}, verbatim from the package ---`, '', f.text, '');
    }
  }
  return lines.join('\n');
}

const licenses = [
  'Third-party license notices for chime-sdk.js',
  '',
  'GENERATED FILE, DO NOT EDIT. Regenerate with: node scripts/vendor-chime-sdk.mjs',
  '',
  'chime-sdk.js is a bundle of amazon-chime-sdk-js and the npm packages it',
  'depends on. This file reproduces the notices those packages ship with. It lists',
  'exactly the packages that contribute code to the bundle, as reported by the',
  'esbuild metafile, and the text under each heading is copied from that package.',
  'Where several packages ship byte-identical text, it is printed once and the',
  'later entries refer back to it.',
  '',
  "The bundle is not covered by this repository's MIT-0 license. Each component",
  'is licensed as stated below.',
  '',
  'Part 1. amazon-chime-sdk-js',
  `  ${sdk.id}  ${sdk.spdx || '(not declared)'}`,
  '',
  'Part 2. Other bundled packages',
  ...others.map((p) => `  ${p.id}  ${p.spdx || '(not declared)'}`),
  '',
  '',
  'PART 1. AMAZON CHIME SDK FOR JAVASCRIPT',
  '',
  section(sdk),
  '',
  'PART 2. OTHER BUNDLED PACKAGES',
  '',
  others.map(section).join('\n\n'),
].join('\n');
writeFileSync(licensesOut, licenses.trimEnd() + '\n');

// A committed, minified megabyte needs to say what produced it — otherwise a
// reader has no way to tell whether it is vendored or hand-written, or how to
// reproduce it. Line 1 is parsed by _chime_sdk_src() in lambda/dashboard_handler.py
// to cache-bust the import on the SDK version, so keep its `@<version>` form.
const banner = [
  `// amazon-chime-sdk-js@${version} — GENERATED FILE, DO NOT EDIT.`,
  '// Regenerate with: node scripts/vendor-chime-sdk.mjs',
  '// Bundles amazon-chime-sdk-js (Apache-2.0, Copyright Amazon.com, Inc. or its affiliates)',
  `// with third-party components under the ${idList} licenses.`,
  "// Their notices are in chime-sdk.LICENSES.txt. Not covered by this repository's MIT-0 license.",
  '',
].join('\n');
const bundled = readFileSync(out, 'utf8');
writeFileSync(out, banner + bundled);

// Fail loudly if tree-shaking or a version bump dropped an export the webview
// imports by name: an ES module import of a missing binding is a hard parse
// error in the browser, and in an RCS webview there is no console to see it in.
//
// A name counts only as a whole identifier, so `export_ConsoleLogger` (the local
// binding esbuild generates) does not stand in for `ConsoleLogger` (the exported
// name). The tail is split once into runs of identifier characters with a literal
// regex and each name is looked up in that set, so no pattern is ever built from
// the names. `$` is an identifier character, so `ConsoleLogger$1` (a name esbuild
// generates to avoid a clash) is a different identifier too.
//
// The names are a fixed, hand-maintained allowlist. Check their shape anyway: an
// entry that cannot be an identifier could never be found in the tail, and the
// build would blame the bundle for a typo in this list.
const EXPORT_NAMES = ['ConsoleLogger', 'LogLevel', 'DefaultDeviceController',
  'MeetingSessionConfiguration', 'DefaultMeetingSession'];
const IDENTIFIER = /^[A-Za-z_$][A-Za-z0-9_$]*$/;
const invalid = EXPORT_NAMES.filter((n) => !IDENTIFIER.test(n));
if (invalid.length) {
  console.error(`error: export allowlist has non-identifier entries: ${invalid.join(', ')}`);
  process.exit(1);
}
const tail = bundled.slice(-4000);
const tailIdentifiers = new Set(tail.match(/[\w$]+/g));
const missing = EXPORT_NAMES.filter((n) => !tailIdentifiers.has(n));
if (missing.length) {
  console.error(`error: the bundle's export list is missing: ${missing.join(', ')}`);
  process.exit(1);
}

console.log(`Wrote ${out} (${Math.round((banner.length + bundled.length) / 1024)} KB)`);
console.log(`Wrote ${licensesOut} (${byId.size} packages)`);
