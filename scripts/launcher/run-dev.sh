#!/bin/bash
#
# AnyHealth local dashboard launcher (macOS/Linux).
#
# Starts the Vite dev server for web/ and opens a browser window to it.
# Self-contained and path-independent: it locates the repo from its own
# location, finds node without relying on an inherited shell PATH (GUI-launched
# apps don't get one), and picks the first free port so it won't collide with
# another Vite instance already using 5173.
#
# Usage:
#   scripts/launcher/run-dev.sh
#   REPO_ROOT=/path/to/repo scripts/launcher/run-dev.sh   # override autodetect
#
# Env overrides:
#   REPO_ROOT   repo root (default: two levels up from this script)
#   PORT_MIN    first port to try  (default 5173)
#   PORT_MAX    last port to try   (default 5183)
#   NO_BROWSER  set to 1 to skip opening a browser

set -u

# --- Locate the repo -------------------------------------------------------
# This script lives at <repo>/scripts/launcher/run-dev.sh. Resolve symlinks so
# it still works when invoked from inside a .app bundle that symlinks to it.
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
WEB_DIR="$REPO_ROOT/web"

PORT_MIN="${PORT_MIN:-5173}"
PORT_MAX="${PORT_MAX:-5183}"

# --- Make sure we can find node (GUI launches have no shell PATH) ----------
# Add the usual suspects, then the newest nvm-installed node if present.
export PATH="/opt/homebrew/bin:/opt/homebrew/opt/node@24/bin:/opt/homebrew/opt/node@22/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
if [ -d "$HOME/.nvm/versions/node" ]; then
  NVM_NODE="$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1)"
  [ -n "${NVM_NODE:-}" ] && export PATH="$NVM_NODE:$PATH"
fi

die() { echo ""; echo "ERROR: $*"; echo ""; echo "Press Return to close."; read -r _; exit 1; }

command -v node >/dev/null 2>&1 || die "node not found. Install Node.js 22 or later (24 LTS recommended) from https://nodejs.org."
[ -d "$WEB_DIR" ] || die "web/ not found under $REPO_ROOT. Is REPO_ROOT correct?"

cd "$WEB_DIR" || die "Could not enter $WEB_DIR"

# --- Pick the first free TCP port in the range -----------------------------
# Uses node itself so we don't depend on lsof/nc being present or consistent.
pick_port() {
  node - "$PORT_MIN" "$PORT_MAX" <<'NODE'
const net = require('net');
const min = parseInt(process.argv[2], 10);
const max = parseInt(process.argv[3], 10);
// Probe one host stack. Free unless the port is actively in use (EADDRINUSE).
// A host that doesn't exist here (EADDRNOTAVAIL / EAFNOSUPPORT — e.g. no IPv6)
// does not make the port "busy", so treat those as free.
function freeOn(port, host) {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.once('error', (e) => resolve(e.code !== 'EADDRINUSE'));
    s.once('listening', () => s.close(() => resolve(true)));
    s.listen(port, host);
  });
}
// Vite binds "localhost", which on macOS resolves to ::1 (IPv6) first, so a
// port already taken by another Vite shows up only on the IPv6 stack. Require
// the port free on BOTH IPv4 and IPv6 or we hand back a port --strictPort will
// then reject.
async function free(port) {
  return (await freeOn(port, '127.0.0.1')) && (await freeOn(port, '::1'));
}
(async () => {
  for (let p = min; p <= max; p++) {
    if (await free(p)) { process.stdout.write(String(p)); return; }
  }
  process.exit(3); // none free
})();
NODE
}

PORT="$(pick_port)"
if [ -z "${PORT:-}" ]; then
  die "No free port between $PORT_MIN and $PORT_MAX. Close another dev server and retry."
fi
URL="http://localhost:$PORT/"

# --- Install deps on first run ---------------------------------------------
# `npm ci` installs exactly what web/package-lock.json pins, and fails if that
# disagrees with package.json. There is no `npm install` fallback on purpose:
# with a missing or stale lockfile it resolves version ranges from the registry
# at that moment and rewrites the lockfile, so a failure is reported rather than
# worked around.
if [ ! -d node_modules ]; then
  echo "Installing dependencies (first run)…"
  if ! npm ci; then
    # npm ci empties node_modules before it installs, so a failed run leaves an
    # empty directory that the check above would take for a finished install.
    rm -rf node_modules
    die "npm ci failed in $WEB_DIR, so the dashboard's dependencies are not installed.
It installs exactly the versions pinned in web/package-lock.json and does not fall
back to 'npm install'. The usual causes are:
  - no route to the npm registry (check your network, proxy or VPN)
  - a Node.js or npm that is too old (this repo needs Node.js 22 or later; 'node --version')
  - web/package-lock.json missing, or out of step with web/package.json
Fix that and launch again. SETUP.md, step 5 (Run the dashboard), has the manual steps."
  fi
fi

# --- Open a browser window once the server is actually up ------------------
open_browser() {
  [ "${NO_BROWSER:-0}" = "1" ] && return
  for _ in $(seq 1 60); do   # up to ~30s
    if curl -sS -m 1 -o /dev/null "$URL" 2>/dev/null; then
      break
    fi
    sleep 0.5
  done
  case "$(uname -s)" in
    Darwin)
      # Prefer a NEW Chrome window via AppleScript — `open`/binary --new-window
      # get silently dropped when Chrome is already running. Fall back to the
      # default browser if Chrome isn't installed.
      if [ -d "/Applications/Google Chrome.app" ]; then
        osascript \
          -e 'on run argv' \
          -e '  tell application "Google Chrome"' \
          -e '    activate' \
          -e '    make new window' \
          -e '    set URL of active tab of front window to (item 1 of argv)' \
          -e '  end tell' \
          -e 'end run' \
          "$URL" >/dev/null 2>&1 || open "$URL"
      else
        open "$URL"
      fi
      ;;
    *)  # Linux
      (xdg-open "$URL" >/dev/null 2>&1 &) || true
      ;;
  esac
}
open_browser &

echo "AnyHealth dashboard starting on $URL"
echo "Press Ctrl-C to stop."
echo ""

# --strictPort: bind exactly the port we chose, or fail loudly — so the URL we
# opened always matches the server.
exec npm run dev -- --port "$PORT" --strictPort
