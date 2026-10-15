/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_API_KEY?: string;
  /**
   * The frontend's version, stamped in by vite.config.ts from scripts/version.mjs.
   * The backend's counterpart is not here: it belongs to whatever deployment this
   * browser is pointed at, so it comes over the wire from GET /api/version.
   */
  readonly VITE_FE_VERSION?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
