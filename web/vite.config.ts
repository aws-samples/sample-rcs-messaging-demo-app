import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
// Dev-server-only endpoint that lists the brand connections this machine holds
// (the wired store plus legacy web/.env.<brand> files) for the brand picker.
import { brandConnections } from './dev-server/brand-connections.mjs';
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
  plugins: [
    react(),
    brandConnections({
      storePath: fileURLToPath(new URL('../.deploy/dashboard-brands.json', import.meta.url)),
      envDir: fileURLToPath(new URL('.', import.meta.url)),
    }),
  ],
  server: {
    port: 5173,
    // Explicit loopback bind: the private default. Passing --host on the command
    // line still overrides it, which the project docs tell users not to do.
    host: 'localhost',
    // Vite's default CORS lets any localhost origin read dev-server responses,
    // including modules that inline VITE_API_KEY from web/.env. Off, so another
    // local page cannot read them cross-origin.
    cors: false,
  },
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
