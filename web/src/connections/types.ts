// Types for the dashboard's brand connections. Pure type declarations: no DOM,
// no storage access and no brand literals. The Brand_Ids the dashboard knows
// about come only from the Connection_Store and the Legacy_Brand_Env_Files that
// the dev server reports, never from a list in this source tree.

/** One raw per-source entry, as the dev-server endpoint returns it. */
export interface SourceEntry {
  source: 'store' | 'envFile';
  /** Validated on the server; the client validates it again. */
  brandId: string;
  /** Raw value, trimmed by the server. */
  apiUrl: string;
  /** May be "" (no key in that source). */
  apiKey: string;
  /** Repo-relative file name, used for the Settings source note. */
  file: string;
}

/** Body of `GET /__rcs-demo/brand-connections`. */
export interface DevConnections {
  version: 1;
  store: {
    status: 'absent' | 'ok' | 'unreadable';
    /** Closed set of reasons; never the file's contents. */
    reason?: string;
    file: string;
    entries: SourceEntry[];
  };
  envFiles: SourceEntry[];
}

/** Where a resolved URL or key came from. */
export type ValueSource =
  | { kind: 'store'; file: string }
  | { kind: 'envFile'; file: string }
  | { kind: 'viteEnv'; name: 'VITE_API_URL' | 'VITE_API_KEY' }
  | { kind: 'saved' }
  | { kind: 'none' };

/** A resolved Available_Connection. */
export interface BrandConnection {
  /** The Brand_Id, or LEGACY_ID for the Legacy_Connection. */
  id: string;
  /** null only for the Legacy_Connection. */
  brandId: string | null;
  source: 'store' | 'envFile' | 'legacy';
  /** Non-empty. Brand_Id connection: normalizeUrl. Legacy: one trailing "/" removed. */
  apiUrl: string;
  /** Resolved key; may be "". */
  apiKey: string;
  urlSource: ValueSource;
  keySource: ValueSource;
  /** True when this Brand_Id connection replaced a Legacy_Connection with the same URL. */
  absorbsLegacy: boolean;
}

/** Notice for a `brand` query parameter that names no Available_Connection. */
export interface UnknownBrandNotice {
  requested: string;
  /** Brand_Ids of the Available_Connections, in Brand_Id order. */
  available: string[];
}

/** The single-brand values that exist today, read by the caller (not here). */
export interface LegacyInput {
  /** `import.meta.env.VITE_API_URL`, or "". */
  viteApiUrl: string;
  /** `import.meta.env.VITE_API_KEY`, or "". */
  viteApiKey: string;
  /** The URL saved in browser storage by Settings / the connect screen, or "". */
  storedApiUrl: string;
  /** The key saved in browser storage by Settings, or "". */
  storedApiKey: string;
}

/** Values saved on the Settings tab for one Brand_Id connection. */
export interface SavedOverride {
  apiUrl?: string;
  apiKey?: string;
}

/** Everything `resolveConnections` needs; gathered by the registry. */
export interface ResolveInput {
  /** Connection_Store entries (empty when the store is absent or unreadable). */
  store: SourceEntry[];
  /** Legacy_Brand_Env_File entries. */
  envFiles: SourceEntry[];
  legacy: LegacyInput;
  /** Settings saves keyed by Brand_Id. */
  saved: Record<string, SavedOverride>;
}
