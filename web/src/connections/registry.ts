// Connection registry for the brand picker: the browser-side runtime store
// that holds the resolved Available_Connections, the Active_Brand and the
// generation counter. It is `useSyncExternalStore`-compatible: `subscribe`
// and `get` are stable functions, and `get()` returns the same snapshot object
// until something changes.
//
// Inputs:
// - In a dev build only, the dev-server endpoint's per-source entries (the
//   Connection_Store and the Legacy_Brand_Env_Files). `import.meta.env.DEV` is
//   `false` in a production build, so the branch, the endpoint path and the
//   fetch are removed from the bundle and a build never asks for connections.
// - Today's single-brand values (`import.meta.env` and `localStorage`) and the
//   per-brand Settings saves, read through `storage.ts`.
//
// A wired brand is offered only if it can really be used: before the first
// render, every Brand_Id connection is checked (verify.ts) and any that fails
// is left out, silently. The dashboard makes no claim about brands it does not
// list. The Legacy_Connection is the operator's own explicit URL and is never
// filtered.
//
// No `console.*` call appears in this module, so no connection object or key
// is ever logged. This file holds no catalog Brand_Id and no brand name.

import { useSyncExternalStore } from 'react';
import {
  LEGACY_ID,
  isValidBrandId,
  normalizeUrl,
  resolveConnections,
  resolveInitialBrand,
  scrubKeys,
  withBrandParam,
  withoutBrandParam,
} from './resolve';
import {
  getSelectedBrand,
  readLegacyInput,
  readSavedOverrides,
  saveApiKey,
  saveApiUrl,
  setSelectedBrand,
} from './storage';
import { fingerprint, verifyConnection } from './verify';
import type {
  BrandConnection,
  DevConnections,
  LegacyInput,
  SavedOverride,
  SourceEntry,
  UnknownBrandNotice,
  ValueSource,
} from './types';

// ---- Public types -------------------------------------------------------------

export type RegistryMode = 'none' | 'single' | 'multi';

export interface RegistryState {
  status: 'loading' | 'ready';
  /** Resolved Available_Connections, in Brand_Id order (Legacy_Connection last). */
  connections: BrandConnection[];
  activeId: string | null;
  /** ++ on every Brand_Switch start and every active URL save that changes the URL. */
  generation: number;
  /** 0, 1, or 2+ Available_Connections. */
  mode: RegistryMode;
  /**
   * True when brands are wired but none could be used (none answered). Distinct
   * from "nothing wired", which needs setup rather than a retry. Carries no
   * names: it makes no claim about which brands exist.
   */
  noneUsable: boolean;
  /** Connection_Store read failure (R1.9): file name and reason only, never contents. */
  storeNotice?: string;
  /** `brand` query value that names no Available_Connection (R4.5); cleared only by dismiss. */
  unknownBrandNotice?: UnknownBrandNotice;
}

/** What a request is bound to. `api.ts`'s Binding is a structural superset. */
export interface BindingRef {
  connectionId: string;
  generation: number;
}

/** Result of a Settings save. */
export interface SaveResult {
  /** False when the connection id is not an Available_Connection (nothing stored). */
  saved: boolean;
  /**
   * Set when a higher-precedence value overrides the saved one, so the saved
   * value stays inactive (R9.5). Names the source only, never a key value.
   */
  inactive?: ValueSource;
}

// ---- Sources --------------------------------------------------------------------

interface Sources {
  store: SourceEntry[];
  envFiles: SourceEntry[];
  /** Built from the store status and reason; undefined when absent or ok. */
  storeNotice?: string;
}

const EMPTY_SOURCES: Sources = { store: [], envFiles: [] };

const DEFAULT_STORE_FILE = '.deploy/dashboard-brands.json';
const FETCH_TIMEOUT_MS = 10_000;

// The server sends a reason from a closed set; anything else is replaced, so a
// changed or hostile response can never put file contents into a notice.
const STORE_REASON_RE = /^(could not be read \([A-Z0-9_]{1,32}\)|not valid JSON|unexpected structure|too large)$/;
// A repo-relative file name: no control characters, short.
const FILE_RE = /^[A-Za-z0-9._/-]{1,200}$/;

function str(v: unknown): string {
  return typeof v === 'string' ? v : '';
}

function safeFile(v: unknown, fallback: string): string {
  const s = str(v);
  return FILE_RE.test(s) ? s : fallback;
}

/** Keep well-formed entries only; copy the store's file name into entries that lack one. */
function cleanEntries(raw: unknown, kind: SourceEntry['source'], fallbackFile: string): SourceEntry[] {
  if (!Array.isArray(raw)) return [];
  const out: SourceEntry[] = [];
  for (const e of raw) {
    if (!e || typeof e !== 'object') continue;
    const r = e as Record<string, unknown>;
    const brandId = str(r.brandId);
    if (!isValidBrandId(brandId)) continue;
    out.push({
      source: kind,
      brandId,
      apiUrl: str(r.apiUrl),
      apiKey: str(r.apiKey),
      file: safeFile(r.file, fallbackFile),
    });
  }
  return out;
}

/** Validate the endpoint body. Anything unexpected reads as no file sources. */
function parseDevConnections(body: unknown): Sources {
  if (!body || typeof body !== 'object') return EMPTY_SOURCES;
  const b = body as Partial<DevConnections> & Record<string, unknown>;
  if (b.version !== 1) return EMPTY_SOURCES;

  const storeRaw = (b.store && typeof b.store === 'object' ? b.store : {}) as Record<string, unknown>;
  const storeFile = safeFile(storeRaw.file, DEFAULT_STORE_FILE);
  const status = str(storeRaw.status);

  const sources: Sources = {
    store: status === 'ok' ? cleanEntries(storeRaw.entries, 'store', storeFile) : [],
    envFiles: cleanEntries(b.envFiles, 'envFile', ''),
  };
  if (status === 'unreadable') {
    const reason = str(storeRaw.reason);
    const shown = STORE_REASON_RE.test(reason) ? reason : 'could not be read';
    sources.storeNotice = `${storeFile} could not be read (${shown}). Other connections still loaded.`;
  }
  return sources;
}

/**
 * Ask the dev server for the per-source entries. Called only from inside an
 * `import.meta.env.DEV` branch, so a production build drops it. Any failure
 * (network error, timeout, non-2xx, bad JSON, unexpected shape) becomes empty
 * sources with no notice.
 */
async function fetchDevConnections(): Promise<Sources> {
  const ctrl = typeof AbortController === 'function' ? new AbortController() : null;
  const timer = ctrl ? setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS) : null;
  try {
    const res = await fetch('/__rcs-demo/brand-connections', {
      method: 'GET',
      headers: { 'X-RCS-Demo-Connections': '1' },
      cache: 'no-store',
      credentials: 'same-origin',
      signal: ctrl?.signal,
    });
    if (!res.ok) return EMPTY_SOURCES;
    return parseDevConnections(await res.json());
  } catch {
    return EMPTY_SOURCES;
  } finally {
    if (timer !== null) clearTimeout(timer);
  }
}

async function readSources(): Promise<Sources> {
  if (import.meta.env.DEV) {
    return fetchDevConnections();
  }
  return EMPTY_SOURCES;
}

// ---- Store internals ------------------------------------------------------------

let state: RegistryState = {
  status: 'loading',
  connections: [],
  activeId: null,
  generation: 0,
  mode: 'none',
  noneUsable: false,
};

let sources: Sources = EMPTY_SOURCES;
/** Inputs of the last resolution, for allKeys(). */
let lastLegacy: LegacyInput = { viteApiUrl: '', viteApiKey: '', storedApiUrl: '', storedApiKey: '' };
let lastSaved: Record<string, SavedOverride> = {};
let storeNoticeDismissed = false;
let unknownNoticeShown = false; // shown at most once per page load (R4.6)
let loadPromise: Promise<void> | null = null;

/**
 * Verdicts from verifyConnection, by fingerprint (id, URL, key), so a rewired
 * brand is checked again. A connection in neither set has not been checked yet.
 * Held in memory only; never rendered or logged.
 */
const okFp = new Set<string>();
const badFp = new Set<string>();
let rechecking = false;
let lastRecheck = 0;
/** Focus-triggered re-checks are spaced out; the Retry button is not. */
const MIN_RECHECK_MS = 5_000;

const listeners = new Set<() => void>();

function setState(patch: Partial<RegistryState>): void {
  const next: RegistryState = { ...state, ...patch };
  // Optional fields: drop undefined so snapshots stay tidy.
  if (next.storeNotice === undefined) delete next.storeNotice;
  if (next.unknownBrandNotice === undefined) delete next.unknownBrandNotice;
  state = next;
  for (const fn of Array.from(listeners)) {
    try {
      fn();
    } catch {
      /* a listener's error must not stop the others */
    }
  }
}

function modeFor(n: number): RegistryMode {
  return n === 0 ? 'none' : n === 1 ? 'single' : 'multi';
}

/** Every resolved connection from the cached sources, before the usable-brand filter. */
function resolveAll(): BrandConnection[] {
  const ids = Array.from(
    new Set([...sources.store, ...sources.envFiles].map((e) => e.brandId).filter(isValidBrandId)),
  );
  lastLegacy = readLegacyInput();
  lastSaved = readSavedOverrides(ids);
  return resolveConnections({
    store: sources.store,
    envFiles: sources.envFiles,
    legacy: lastLegacy,
    saved: lastSaved,
  });
}

/** The Available_Connections: all of them except Brand_Id connections that failed their check. */
function resolveNow(): BrandConnection[] {
  return resolveAll().filter((c) => !badFp.has(fingerprint(c)));
}

/** True when brands are wired but every one failed its check. */
function noneUsableFor(conns: BrandConnection[]): boolean {
  return conns.length === 0 && badFp.size > 0;
}

/**
 * Check the Brand_Id connections that have no verdict yet (and, with
 * `retryFailed`, the ones that failed), all at once. The Legacy_Connection is
 * never checked. Verdicts for connections that are no longer wired are dropped,
 * so a removed brand cannot leave a stale "none usable" behind.
 */
async function verifyPending(retryFailed = false): Promise<void> {
  const all = resolveAll();
  const live = new Set(all.map(fingerprint));
  for (const fp of Array.from(okFp)) if (!live.has(fp)) okFp.delete(fp);
  for (const fp of Array.from(badFp)) if (!live.has(fp)) badFp.delete(fp);

  const todo = all.filter((c) => {
    if (c.brandId === null) return false;
    const fp = fingerprint(c);
    return !okFp.has(fp) && (retryFailed || !badFp.has(fp));
  });
  if (todo.length === 0) return;
  const verdicts = await Promise.all(todo.map((c) => verifyConnection(c)));
  todo.forEach((c, i) => {
    const fp = fingerprint(c);
    if (verdicts[i]) {
      okFp.add(fp);
      badFp.delete(fp);
    } else {
      badFp.add(fp);
      okFp.delete(fp);
    }
  });
}

function find(conns: BrandConnection[], id: string | null): BrandConnection | undefined {
  return id === null ? undefined : conns.find((c) => c.id === id);
}

function currentSearch(): string {
  try {
    return typeof location !== 'undefined' ? location.search : '';
  } catch {
    return '';
  }
}

function queryBrand(): string | null {
  try {
    return new URLSearchParams(currentSearch()).get('brand');
  } catch {
    return null;
  }
}

/** Replace the current history entry's query; never reloads, keeps path and hash. */
function replaceSearch(next: string): void {
  try {
    if (next === location.search) return;
    history.replaceState(null, '', location.pathname + next + location.hash);
  } catch {
    /* history unavailable: the address bar keeps its value */
  }
}

/**
 * Bring the address bar in line with the mode and the Active_Brand:
 * multi with a Brand_Id active sets `brand`; otherwise (single, or the
 * Legacy_Connection active) removes it. Mode `none` leaves the address alone.
 */
function syncAddress(): void {
  const active = find(state.connections, state.activeId);
  if (state.mode === 'none' || !active) return;
  const search = currentSearch();
  if (state.mode === 'multi' && active.brandId !== null) {
    replaceSearch(withBrandParam(search, active.brandId));
  } else if (queryBrand() !== null) {
    replaceSearch(withoutBrandParam(search));
  }
}

/** Save the Active_Brand's Brand_Id as the previous selection (no-op for the Legacy_Connection). */
function persistSelection(): void {
  const active = find(state.connections, state.activeId);
  if (active && active.brandId !== null) setSelectedBrand(active.brandId);
}

/**
 * Pick the Active_Brand after a re-resolution. Keeps the current one when it is
 * still Available; otherwise prefers the connection that now carries the
 * previous URL (for example a Brand_Id connection that absorbed the
 * Legacy_Connection), and otherwise resolves as at load.
 */
function pickActive(conns: BrandConnection[], prevId: string | null, prevUrl: string | null): string | null {
  if (conns.length === 0) return null;
  if (find(conns, prevId)) return prevId;
  if (prevUrl) {
    const same = conns.find((c) => normalizeUrl(c.apiUrl) === normalizeUrl(prevUrl));
    if (same) return same.id;
  }
  return resolveInitialBrand(conns, queryBrand(), getSelectedBrand()).activeId;
}

/**
 * Re-resolve from the cached sources. Bumps the generation when the Active_Brand
 * changes, or when `bumpIfUrlChanged` and the active URL changed.
 */
function reresolve(bumpIfUrlChanged: boolean): void {
  const prev = find(state.connections, state.activeId);
  const conns = resolveNow();
  const activeId = pickActive(conns, state.activeId, prev?.apiUrl ?? null);
  const next = find(conns, activeId);
  const idChanged = activeId !== state.activeId;
  const urlChanged = !!prev && !!next && prev.apiUrl !== next.apiUrl;
  const bump = idChanged || (bumpIfUrlChanged && urlChanged);
  setState({
    connections: conns,
    activeId,
    mode: modeFor(conns.length),
    noneUsable: noneUsableFor(conns),
    generation: bump ? state.generation + 1 : state.generation,
  });
  if (idChanged) persistSelection();
  syncAddress();
}

function inactiveSource(src: ValueSource): ValueSource | undefined {
  return src.kind === 'store' || src.kind === 'envFile' || src.kind === 'viteEnv' ? src : undefined;
}

async function doLoad(): Promise<void> {
  sources = await readSources();
  // Nothing renders until every wired brand has been checked, so the dashboard
  // never opens on a brand that cannot load.
  await verifyPending();
  const conns = resolveNow();
  let activeId: string | null = null;
  let notice: UnknownBrandNotice | undefined;
  if (conns.length > 0) {
    const r = resolveInitialBrand(conns, queryBrand(), getSelectedBrand());
    activeId = r.activeId;
    if (r.notice && !unknownNoticeShown) {
      notice = r.notice;
      unknownNoticeShown = true;
    }
  }
  setState({
    status: 'ready',
    connections: conns,
    activeId,
    mode: modeFor(conns.length),
    noneUsable: noneUsableFor(conns),
    storeNotice: storeNoticeDismissed ? undefined : scrubbedStoreNotice(),
    unknownBrandNotice: notice ?? state.unknownBrandNotice,
  });
  persistSelection();
  syncAddress();
}

function scrubbedStoreNotice(): string | undefined {
  return sources.storeNotice ? scrubKeys(sources.storeNotice, allKeys()) : undefined;
}

function allKeys(): string[] {
  const keys = new Set<string>();
  const add = (k: unknown) => {
    if (typeof k === 'string' && k !== '') keys.add(k);
  };
  for (const c of state.connections) add(c.apiKey);
  for (const e of sources.store) add(e.apiKey);
  for (const e of sources.envFiles) add(e.apiKey);
  add(lastLegacy.viteApiKey);
  add(lastLegacy.storedApiKey);
  for (const id of Object.keys(lastSaved)) add(lastSaved[id]?.apiKey?.trim());
  return Array.from(keys);
}

// ---- Public API ---------------------------------------------------------------------

export const registry = {
  /**
   * Gather the sources, resolve the Available_Connections and the Active_Brand,
   * save the selection and update the address bar. Runs once per page load;
   * later calls return the same promise. Status stays `loading` until done, and
   * the shell sends no API request before `ready` (R1.1, R4.1).
   */
  load(): Promise<void> {
    if (!loadPromise) loadPromise = doLoad();
    return loadPromise;
  },

  /**
   * Fetch the sources again and re-resolve without a page reload (for example
   * after the "Connect to your deployment" screen saves a URL, R2.7). Keeps the
   * Active_Brand when it is still Available.
   */
  async reload(): Promise<void> {
    if (state.status !== 'ready') {
      // The first load reads everything fresh already.
      await registry.load();
      return;
    }
    sources = await readSources();
    await verifyPending();
    reresolve(true);
    setState({ storeNotice: storeNoticeDismissed ? undefined : scrubbedStoreNotice() });
  },

  /**
   * Quietly look again: pick up a newly wired brand and let a brand that failed
   * its check back in if it answers now. It only ever adds, and it never swaps
   * out the brand the operator is using. Called when the tab regains focus
   * (spaced out) and by the Retry button on the "none answered" screen (`force`).
   */
  async recheck(opts: { force?: boolean } = {}): Promise<void> {
    if (state.status !== 'ready' || rechecking) return;
    if (!opts.force && Date.now() - lastRecheck < MIN_RECHECK_MS) return;
    rechecking = true;
    try {
      const before = resolveNow().map(fingerprint).join('\u0001');
      sources = await readSources();
      await verifyPending(true);
      // A glitch must not evict the brand in use: its own session reports its errors.
      // Matched by id, not by fingerprint: a rewired brand has a new one.
      const inUse = resolveAll().find((c) => c.id === state.activeId);
      if (inUse) badFp.delete(fingerprint(inUse));
      const after = resolveNow().map(fingerprint).join('\u0001');
      if (before !== after || state.noneUsable !== noneUsableFor(resolveNow())) {
        reresolve(false);
      }
    } finally {
      rechecking = false;
      lastRecheck = Date.now();
    }
  },

  subscribe(fn: () => void): () => void {
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  },

  get(): RegistryState {
    return state;
  },

  /** The Active_Brand's connection, or null before load / with no connection. */
  active(): BrandConnection | null {
    return find(state.connections, state.activeId) ?? null;
  },

  /** The connection's current key, read when a request is issued; "" when none. */
  keyFor(connectionId: string): string {
    return find(state.connections, connectionId)?.apiKey ?? '';
  },

  /** True while the binding's connection is active and its generation is current. */
  isCurrent(b: BindingRef): boolean {
    return !!b && state.activeId === b.connectionId && state.generation === b.generation;
  },

  /**
   * Start a Brand_Switch: make `id` active, bump the generation, save the
   * selection and update `?brand=` (R4.7, R4.8, R6.10). Selecting the active
   * connection, or an id that is not Available, changes nothing.
   */
  setActive(id: string): void {
    if (id === state.activeId || !find(state.connections, id)) return;
    setState({ activeId: id, generation: state.generation + 1 });
    persistSelection();
    syncAddress();
  },

  /**
   * Save an API URL from Settings for one connection and re-resolve. For the
   * Legacy_Connection it lands in today's entry; when it is the active
   * connection and its effective URL changes, the generation is bumped so the
   * session reloads (R9.3). For a Brand_Id connection the saved URL is stored
   * but inactive, and the result names the source in use (R9.5).
   */
  saveUrl(id: string, url: string): SaveResult {
    const c = find(state.connections, id);
    if (!c) return { saved: false };
    const value = str(url).trim().replace(/\/+$/, '');
    saveApiUrl(c, value);
    reresolve(id === state.activeId);
    const after = find(state.connections, id) ?? find(state.connections, state.activeId);
    const inactive = c.brandId !== null ? c.urlSource : after ? inactiveSource(after.urlSource) : undefined;
    return inactive ? { saved: true, inactive } : { saved: true };
  },

  /**
   * Save an API key from Settings for one connection and re-resolve. An empty
   * value clears the saved key. The generation is not changed: the next request
   * reads the new key, and requests already issued keep theirs (R5.5, R9.3).
   */
  saveKey(id: string, key: string): SaveResult {
    const c = find(state.connections, id);
    if (!c) return { saved: false };
    saveApiKey(c, str(key).trim());
    reresolve(false);
    const after = find(state.connections, id);
    const inactive = after ? inactiveSource(after.keySource) : undefined;
    return inactive ? { saved: true, inactive } : { saved: true };
  },

  /** Every known non-empty key, for scrubKeys (R11.5). */
  allKeys,

  /** Remove the unknown-`brand` notice until the next page load (R4.6). */
  dismissUnknownBrandNotice(): void {
    if (state.unknownBrandNotice) setState({ unknownBrandNotice: undefined });
  },

  /** Remove the Connection_Store notice until the next page load (R1.9). */
  dismissStoreNotice(): void {
    storeNoticeDismissed = true;
    if (state.storeNotice) setState({ storeNotice: undefined });
  },
};

/** React hook over the registry snapshot. */
export function useRegistry(): RegistryState {
  return useSyncExternalStore(registry.subscribe, registry.get, registry.get);
}

export { LEGACY_ID };
