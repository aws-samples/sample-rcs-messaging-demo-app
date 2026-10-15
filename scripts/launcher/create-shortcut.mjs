#!/usr/bin/env node
/*
 * Cross-platform entry point for creating the AnyHealth desktop launcher.
 * Detects the OS and runs the matching generator:
 *   macOS   -> make-desktop-shortcut.sh
 *   Windows -> make-desktop-shortcut.ps1
 *   Linux   -> not supported as a desktop icon; prints how to run the dashboard.
 *
 * Invoked via `npm run create-shortcut` from web/, or directly with `node`.
 */
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { platform } from 'node:os';

const here = dirname(fileURLToPath(import.meta.url));

function run(cmd, args) {
  const r = spawnSync(cmd, args, { stdio: 'inherit' });
  process.exit(r.status ?? 1);
}

switch (platform()) {
  case 'darwin':
    run('bash', [join(here, 'make-desktop-shortcut.sh')]);
    break;
  case 'win32':
    run('powershell', [
      '-NoProfile',
      '-ExecutionPolicy', 'Bypass',
      '-File', join(here, 'make-desktop-shortcut.ps1'),
    ]);
    break;
  default:
    console.log(
      'Desktop shortcuts are supported on macOS and Windows.\n' +
      'On Linux, start the dashboard directly with:\n' +
      `  bash ${join(here, 'run-dev.sh')}\n` +
      'or the usual `npm run dev` from the web/ directory.'
    );
    process.exit(0);
}
