import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
// The frontend half of the version string in the dashboard status bar. Computed
// at build (and dev-server start) time from version.json plus the commit count
// for web/ — see scripts/version.mjs, which the CDK app calls as a CLI for the
// backend half so both numbers come from one implementation.
import { version } from '../scripts/version.mjs';

// Handed to the app as a VITE_-prefixed environment variable rather than through
// `define`: Vite applies `define` substitutions on a production build but not to
// source served by the dev server, so a plain `__FE_VERSION__` global is a
// ReferenceError in `npm run dev`. Vite collects VITE_* out of process.env after
// this module has run, so setting it here reaches import.meta.env in both modes.
// Does not override a value already set (web/.env, or the shell), so a build can
// still be stamped by hand.
process.env.VITE_FE_VERSION = process.env.VITE_FE_VERSION || version('frontend');

export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  // amazon-chime-sdk-js is distributed as CommonJS, and parts of it (and its
  // transitive deps) reference Node's `global`. Vite does not shim `global`, so
  // without an alias, loading the SDK throws "ReferenceError: global is not
  // defined" before any of our code runs. Aliasing it to globalThis, as the
  // Chime SDK's Vite guidance describes, lets the SDK load in the browser.
  define: { global: 'globalThis' },
  // …and again here, because `define` above does not reach dev-mode dependency
  // pre-bundling. Vite pre-bundles node_modules with esbuild before its own
  // transform pipeline ever sees them, so without this the SDK still throws
  // "global is not defined" in `npm run dev` while `npm run build` is fine.
  optimizeDeps: { esbuildOptions: { define: { global: 'globalThis' } } },
});
