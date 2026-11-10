// Pure connection resolution for the brand picker. No DOM, no storage, no
// fetch: the registry gathers the inputs (dev-server entries, today's
// single-brand values, Settings saves) and passes them in, so every function
// here is deterministic and safe to call from a property check.
//
// This file holds no catalog Brand_Id and no brand display name. Brand_Ids come
// only from the entries passed in.

import type {
  BrandConnection,
  ResolveInput,
  SavedOverride,
  SourceEntry,
  UnknownBrandNotice,
  ValueSource,
} from './types';

/** Connection id of the Legacy_Connection. "~" can never start a valid Brand_Id. */
export const LEGACY_ID = '~legacy';

const BRAND_ID_RE = /^[a-z][a-z0-9-]{0,31}$/;

/** Lowercase ASCII letters, digits and hyphens, starting with a letter, at most 32 characters. */
export function isValidBrandId(s: string): boolean {
  return typeof s === 'string' && BRAND_ID_RE.test(s);
}

/** Trim, then remove every trailing "/". */
export function normalizeUrl(u: string): string {
  return str(u).trim().replace(/\/+$/, '');
}

/** Compare by UTF-16 code unit (not locale), as "Brand_Id order" requires. */
function byCharCode(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** JSON can carry anything; a non-string field reads as "". */
function str(v: unknown): string {
  return typeof v === 'string' ? v : '';
}

function savedFor(saved: Record<string, SavedOverride>, id: string): SavedOverride {
  // Own properties only, so an id such as "constructor" never reads Object.prototype.
  return saved && Object.prototype.hasOwnProperty.call(saved, id) ? saved[id] ?? {} : {};
}

const RANK: Record<BrandConnection['source'], number> = { store: 0, envFile: 1, legacy: 2 };

/**
 * Resolve the Available_Connections.
 *
 * 1. Drop entries whose Brand_Id is invalid.
 * 2. Keep only Available entries (URL non-empty after trimming and trailing-slash removal).
 * 3. Per Brand_Id, the Available store entry wins over the Available env-file entry;
 *    URL and key come from that one entry, never mixed.
 * 4. A saved key applies only when the winning entry's key is empty. A saved URL is
 *    never active for a Brand_Id connection (a source always supplies its URL).
 * 5. Add the Legacy_Connection with today's expressions.
 * 6. De-duplicate by normalized URL: lowest (source rank, Brand_Id) wins; a Brand_Id
 *    winner whose group held the Legacy_Connection is marked absorbsLegacy.
 * 7. Sort by Brand_Id (char code), the Legacy_Connection last.
 *
 * The result does not depend on the order of the input entries.
 */
export function resolveConnections(input: ResolveInput): BrandConnection[] {
  const pick = new Map<string, { kind: 'store' | 'envFile'; entry: SourceEntry }>();

  const consider = (kind: 'store' | 'envFile', entries: SourceEntry[] | undefined) => {
    for (const raw of Array.isArray(entries) ? entries : []) {
      if (!raw || typeof raw !== 'object') continue;
      const brandId = str(raw.brandId);
      if (!isValidBrandId(brandId)) continue;
      const entry: SourceEntry = {
        source: kind,
        brandId,
        apiUrl: str(raw.apiUrl),
        apiKey: str(raw.apiKey),
        file: str(raw.file),
      };
      if (normalizeUrl(entry.apiUrl) === '') continue; // not Available
      const prev = pick.get(brandId);
      if (!prev || RANK[kind] < RANK[prev.kind] || (kind === prev.kind && entryLess(entry, prev.entry))) {
        pick.set(brandId, { kind, entry });
      }
    }
  };
  consider('store', input.store);
  consider('envFile', input.envFiles);

  const candidates: BrandConnection[] = [];
  for (const [brandId, { kind, entry }] of pick) {
    const urlSource: ValueSource = { kind, file: entry.file };
    let apiKey = entry.apiKey;
    let keySource: ValueSource = { kind, file: entry.file };
    if (apiKey.trim() === '') {
      const savedKey = str(savedFor(input.saved, brandId).apiKey).trim();
      if (savedKey) {
        apiKey = savedKey;
        keySource = { kind: 'saved' };
      } else {
        apiKey = '';
        keySource = { kind: 'none' };
      }
    }
    candidates.push({
      id: brandId,
      brandId,
      source: kind,
      apiUrl: normalizeUrl(entry.apiUrl),
      apiKey,
      urlSource,
      keySource,
      absorbsLegacy: false,
    });
  }

  const legacy = resolveLegacy(input.legacy);
  if (legacy) candidates.push(legacy);

  // De-duplicate by normalized URL.
  const groups = new Map<string, BrandConnection[]>();
  for (const c of candidates) {
    const k = normalizeUrl(c.apiUrl);
    const g = groups.get(k);
    if (g) g.push(c);
    else groups.set(k, [c]);
  }
  const out: BrandConnection[] = [];
  for (const g of groups.values()) {
    let win = g[0];
    for (const c of g) if (candLess(c, win)) win = c;
    const hadLegacy = g.some((c) => c.source === 'legacy');
    out.push(win.brandId !== null && hadLegacy ? { ...win, absorbsLegacy: true } : win);
  }

  out.sort((a, b) => {
    if (a.brandId === null) return b.brandId === null ? 0 : 1;
    if (b.brandId === null) return -1;
    return byCharCode(a.brandId, b.brandId);
  });
  return out;
}

/** Tie-break for two same-source entries of one Brand_Id, so input order never matters. */
function entryLess(a: SourceEntry, b: SourceEntry): boolean {
  return (
    byCharCode(a.apiUrl, b.apiUrl) ||
    byCharCode(a.apiKey, b.apiKey) ||
    byCharCode(a.file, b.file)
  ) < 0;
}

function candLess(a: BrandConnection, b: BrandConnection): boolean {
  const r = RANK[a.source] - RANK[b.source];
  if (r !== 0) return r < 0;
  return byCharCode(a.brandId ?? '', b.brandId ?? '') < 0;
}

/** Today's single-brand expressions, unchanged. Returns null when not Available. */
function resolveLegacy(l: ResolveInput['legacy'] | undefined): BrandConnection | null {
  const viteUrl = str(l?.viteApiUrl);
  const viteKey = str(l?.viteApiKey);
  const storedUrl = str(l?.storedApiUrl);
  const storedKey = str(l?.storedApiKey);

  const apiUrl = (viteUrl || storedUrl).replace(/\/$/, '');
  if (apiUrl.trim() === '') return null;
  const apiKey = viteKey || storedKey;

  const urlSource: ValueSource = viteUrl ? { kind: 'viteEnv', name: 'VITE_API_URL' } : { kind: 'saved' };
  const keySource: ValueSource = viteKey
    ? { kind: 'viteEnv', name: 'VITE_API_KEY' }
    : storedKey
      ? { kind: 'saved' }
      : { kind: 'none' };

  return {
    id: LEGACY_ID,
    brandId: null,
    source: 'legacy',
    apiUrl,
    apiKey,
    urlSource,
    keySource,
    absorbsLegacy: false,
  };
}

/**
 * Choose the Active_Brand at load: the `brand` query value if it names an
 * Available Brand_Id (exact, case-sensitive), else the saved selection if it
 * does, else the first Available connection with a Brand_Id, else the
 * Legacy_Connection. A non-empty unmatched query value yields a notice.
 */
export function resolveInitialBrand(
  avail: BrandConnection[],
  queryBrand: string | null,
  savedId: string | null,
): { activeId: string; notice?: UnknownBrandNotice } {
  const ids = avail.filter((c) => c.brandId !== null).map((c) => c.brandId as string);
  const has = (v: string | null): v is string => !!v && ids.includes(v);

  let notice: UnknownBrandNotice | undefined;
  if (queryBrand && !has(queryBrand)) notice = { requested: queryBrand, available: [...ids] };

  let activeId: string;
  if (has(queryBrand)) activeId = queryBrand;
  else if (has(savedId)) activeId = savedId;
  else if (ids.length > 0) activeId = ids[0];
  else activeId = avail.length > 0 ? avail[0].id : LEGACY_ID;

  return notice ? { activeId, notice } : { activeId };
}

// ---- Query string helpers ---------------------------------------------------
// These work on the raw "&"-separated segments, so every other parameter keeps
// its exact bytes and relative order. The result is "" or starts with "?".
// Pass it to history.replaceState together with location.pathname and
// location.hash: an empty relative URL would keep the current query.

function segments(search: string): string[] {
  const q = str(search).replace(/^\?/, '');
  return q === '' ? [] : q.split('&');
}

function isBrandSegment(seg: string): boolean {
  const name = seg.split('=')[0].replace(/\+/g, ' ');
  try {
    return decodeURIComponent(name) === 'brand';
  } catch {
    return name === 'brand';
  }
}

function join(segs: string[]): string {
  return segs.length === 0 ? '' : `?${segs.join('&')}`;
}

/** Set `brand` to the Brand_Id (one occurrence, at the first one's position); keep all other parameters. */
export function withBrandParam(search: string, brandId: string): string {
  const next = `brand=${encodeURIComponent(brandId)}`;
  const out: string[] = [];
  let placed = false;
  for (const seg of segments(search)) {
    if (isBrandSegment(seg)) {
      if (!placed) {
        out.push(next);
        placed = true;
      }
    } else {
      out.push(seg);
    }
  }
  if (!placed) out.push(next);
  return join(out);
}

/** Remove every `brand` parameter; keep all other parameters. */
export function withoutBrandParam(search: string): string {
  return join(segments(search).filter((seg) => !isBrandSegment(seg)));
}

// ---- Settings URL validation ------------------------------------------------

const MAX_URL_LENGTH = 2048;

/**
 * Validate an API URL entered on the Settings tab for the connection `selfId`.
 * Accepts a trimmed, non-empty value of at most 2048 characters that starts with
 * http:// or https:// and, after trailing-slash removal, matches no other
 * connection's URL. Returns the normalized URL on success.
 */
export function validateApiUrl(
  input: string,
  selfId: string,
  all: BrandConnection[],
  labelOf: (id: string) => string,
): { ok: true; url: string } | { ok: false; error: string } {
  const trimmed = str(input).trim();
  if (trimmed === '') return { ok: false, error: 'Enter an API URL.' };
  if (trimmed.length > MAX_URL_LENGTH) {
    return { ok: false, error: `The API URL is longer than ${MAX_URL_LENGTH} characters.` };
  }
  if (!trimmed.startsWith('http://') && !trimmed.startsWith('https://')) {
    return { ok: false, error: 'The API URL must start with http:// or https://.' };
  }
  const url = normalizeUrl(trimmed);
  const dup = all.find((c) => c.id !== selfId && normalizeUrl(c.apiUrl) === url);
  if (dup) {
    return { ok: false, error: `This API URL is already used by ${labelOf(dup.id)}.` };
  }
  return { ok: true, url };
}

// ---- Key scrubbing ----------------------------------------------------------

const MASK = '••••';

/**
 * Replace every occurrence of every non-empty key with a mask, longest key
 * first so a key that contains a shorter one is masked whole. Text that holds
 * no key is returned unchanged.
 */
export function scrubKeys(text: string, keys: string[]): string {
  const src = str(text);
  const list = Array.from(new Set((Array.isArray(keys) ? keys : []).filter((k) => typeof k === 'string' && k !== '')));
  if (list.length === 0 || !list.some((k) => src.includes(k))) return src;
  list.sort((a, b) => b.length - a.length || byCharCode(a, b));
  let out = src;
  for (const k of list) out = out.split(k).join(MASK);
  // A key made of mask characters could survive or reappear; fail closed.
  return list.some((k) => out.includes(k)) ? '' : out;
}

// ---- Labels -----------------------------------------------------------------

/**
 * Brand_Label: the loaded brandName when non-empty, otherwise the Brand_Id, or
 * for the Legacy_Connection the host part of its API URL.
 */
export function brandLabel(c: BrandConnection, loaded?: { name?: string }): string {
  const name = str(loaded?.name).trim();
  if (name) return name;
  if (c.brandId) return c.brandId;
  try {
    return new URL(c.apiUrl).host || c.apiUrl;
  } catch {
    return c.apiUrl;
  }
}
