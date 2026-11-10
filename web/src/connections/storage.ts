// Browser storage for the brand picker: per-connection target phone, inbound
// deep link, saved API URL and saved API key, plus the previously selected
// Brand_Id.
//
// Two columns:
// - Legacy_Connection: the same `localStorage` entries as before this feature.
//   URL, key and deep link delegate to the existing `config.ts` functions,
//   whose bodies are unchanged, so the single-brand path runs the same reads
//   and writes as today. The target phone has no `config.ts` function (App.tsx
//   reads it directly), so it is read and written here under the same entry.
// - Brand_Id connection: `rcs-demo.brand.<id>.<field>`. A connection that
//   absorbsLegacy falls back to the legacy phone and deep link until a value
//   is saved for it.
//
// Every `localStorage` access is wrapped in try/catch: a storage that throws
// (private mode, disabled storage, quota) reads as "nothing saved" and a save
// is silently dropped. No exception escapes this module.
//
// This file holds no catalog Brand_Id and no brand display name. The
// `anyhealth_*` names below are today's internal entry names (they must match
// the ones in `config.ts` and `App.tsx`), not a brand selection.
import { getApiKey, getApiUrl, getDeepLink, setApiKey, setApiUrl, setDeepLink } from '../config';
import { isValidBrandId } from './resolve';
import type { BrandConnection, LegacyInput, SavedOverride } from './types';

/** The fields of a connection this module needs. */
export type ConnectionRef = Pick<BrandConnection, 'brandId' | 'absorbsLegacy'>;

// Today's single-brand entries (same names as config.ts / App.tsx).
const LEGACY_PHONE = 'anyhealth_phone';
const LEGACY_API_URL = 'anyhealth_api_url';
const LEGACY_API_KEY = 'anyhealth_api_key';

const PREFIX = 'rcs-demo.brand.';
const SELECTED_BRAND = 'rcs-demo.selectedBrand';

type Field = 'phone' | 'deepLink' | 'apiUrl' | 'apiKey';

// ---- Guarded localStorage primitives ----------------------------------------

/** The stored value, or null when unset or storage is unavailable. */
function read(key: string): string | null {
  try {
    const v = localStorage.getItem(key);
    return typeof v === 'string' ? v : null;
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* ignore: storage unavailable */
  }
}

/** Key for a Brand_Id field, or null for an invalid Brand_Id (never builds an arbitrary key). */
function brandKey(brandId: string, field: Field): string | null {
  return isValidBrandId(brandId) ? `${PREFIX}${brandId}.${field}` : null;
}

function readBrand(brandId: string, field: Field): string | null {
  const k = brandKey(brandId, field);
  return k ? read(k) : null;
}

function writeBrand(brandId: string, field: Field, value: string): void {
  const k = brandKey(brandId, field);
  if (k) write(k, value);
}

/** Wrap a config.ts call: those functions already guard storage, but `import.meta.env` access stays guarded too. */
function safe<T>(fn: () => T, fallback: T): T {
  try {
    return fn();
  } catch {
    return fallback;
  }
}

// ---- Target phone -------------------------------------------------------------

/**
 * The saved target phone (raw, as saved; the caller normalizes).
 * Legacy_Connection: `anyhealth_phone`. Brand_Id connection: its own entry,
 * falling back to `anyhealth_phone` when it absorbsLegacy and nothing is saved.
 */
export function getPhone(c: ConnectionRef): string {
  if (c.brandId === null) return read(LEGACY_PHONE) ?? '';
  const own = readBrand(c.brandId, 'phone');
  if (own !== null) return own;
  return c.absorbsLegacy ? read(LEGACY_PHONE) ?? '' : '';
}

export function setPhone(c: ConnectionRef, phone: string): void {
  if (c.brandId === null) write(LEGACY_PHONE, phone);
  else writeBrand(c.brandId, 'phone', phone);
}

// ---- Inbound deep link --------------------------------------------------------

/**
 * Legacy_Connection: `VITE_DEEP_LINK || anyhealth_deep_link` (config.ts).
 * Brand_Id connection: its own entry, falling back to the legacy value when it
 * absorbsLegacy and nothing is saved.
 */
export function getConnectionDeepLink(c: ConnectionRef): string {
  if (c.brandId === null) return safe(getDeepLink, '');
  const own = readBrand(c.brandId, 'deepLink');
  if (own !== null) return own;
  return c.absorbsLegacy ? safe(getDeepLink, '') : '';
}

export function setConnectionDeepLink(c: ConnectionRef, url: string): void {
  if (c.brandId === null) {
    safe(() => setDeepLink(url), undefined);
    return;
  }
  // Same normalization as config.ts setDeepLink.
  writeBrand(c.brandId, 'deepLink', url.trim());
}

// ---- Saved API URL and API key (Settings) ---------------------------------------

/**
 * Save an API URL from Settings. Legacy_Connection: `anyhealth_api_url` via
 * config.ts. Brand_Id connection: stored but inactive (a source always
 * supplies its URL); Settings reports it as such.
 */
export function saveApiUrl(c: ConnectionRef, url: string): void {
  if (c.brandId === null) {
    safe(() => setApiUrl(url), undefined);
    return;
  }
  writeBrand(c.brandId, 'apiUrl', url.replace(/\/+$/, ''));
}

/** Save an API key from Settings. Legacy_Connection: `anyhealth_api_key` via config.ts. */
export function saveApiKey(c: ConnectionRef, key: string): void {
  if (c.brandId === null) {
    safe(() => setApiKey(key), undefined);
    return;
  }
  writeBrand(c.brandId, 'apiKey', key);
}

/** The values saved on Settings for one Brand_Id (absent fields were never saved). */
export function readSavedOverride(brandId: string): SavedOverride {
  const out: SavedOverride = {};
  const apiUrl = readBrand(brandId, 'apiUrl');
  const apiKey = readBrand(brandId, 'apiKey');
  if (apiUrl !== null) out.apiUrl = apiUrl;
  if (apiKey !== null) out.apiKey = apiKey;
  return out;
}

/** Settings saves for the given Brand_Ids, keyed by Brand_Id. Invalid ids are skipped. */
export function readSavedOverrides(brandIds: string[]): Record<string, SavedOverride> {
  const out: Record<string, SavedOverride> = Object.create(null);
  for (const id of Array.isArray(brandIds) ? brandIds : []) {
    if (typeof id === 'string' && isValidBrandId(id)) out[id] = readSavedOverride(id);
  }
  return out;
}

/**
 * Today's single-brand inputs for the Legacy_Connection. The env values are
 * the same `import.meta.env` reads config.ts makes; the stored values are the
 * raw `anyhealth_api_url` / `anyhealth_api_key` entries, so `resolveLegacy`
 * reproduces config.ts `getApiUrl()` / `getApiKey()` exactly.
 */
export function readLegacyInput(): LegacyInput {
  const env = safe(() => import.meta.env, {} as ImportMetaEnv);
  return {
    viteApiUrl: typeof env.VITE_API_URL === 'string' ? env.VITE_API_URL : '',
    viteApiKey: typeof env.VITE_API_KEY === 'string' ? env.VITE_API_KEY : '',
    storedApiUrl: read(LEGACY_API_URL) ?? '',
    storedApiKey: read(LEGACY_API_KEY) ?? '',
  };
}

/** The Legacy_Connection URL and key exactly as config.ts resolves them today. */
export function legacyApiUrl(): string {
  return safe(getApiUrl, '');
}

export function legacyApiKey(): string {
  return safe(getApiKey, '');
}

// ---- Previously selected Brand_Id ---------------------------------------------

/** The previously selected Brand_Id, or null when unset, invalid or unreadable. */
export function getSelectedBrand(): string | null {
  const v = read(SELECTED_BRAND);
  return v !== null && isValidBrandId(v) ? v : null;
}

/** Save the selected Brand_Id. A null (Legacy_Connection) or invalid id is not saved. */
export function setSelectedBrand(brandId: string | null): void {
  if (brandId !== null && isValidBrandId(brandId)) write(SELECTED_BRAND, brandId);
}
