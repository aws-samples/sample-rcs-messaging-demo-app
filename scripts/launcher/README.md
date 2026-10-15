# Desktop launcher for the dashboard

An optional convenience: a double-click desktop icon that starts the Vite dev
server for `web/` and opens a browser window to it. Nothing here is required to
run the demo — it's a shortcut around `cd web && npm run dev`.

## Create the shortcut

From the `web/` directory:

```bash
npm run create-shortcut
```

That detects your OS and runs the matching generator. You can also run the
generators directly:

- **macOS:** `bash scripts/launcher/make-desktop-shortcut.sh`
- **Windows:** `powershell -ExecutionPolicy Bypass -File scripts\launcher\make-desktop-shortcut.ps1`

A **`<BrandName> Dashboard`** icon appears on your Desktop (the brand name and,
on macOS, the icon come from `content/brand.md` and `media/logo.png`). Put it
elsewhere with `DEST_DIR=~/Applications npm run create-shortcut` (macOS) or the
`-DestDir` parameter (Windows).

## What double-clicking it does

1. Opens a terminal window and runs `run-dev.sh` (macOS/Linux) or `run-dev.bat`
   (Windows) from this repo.
2. Picks the **first free port** in `5173`–`5183` — so it won't collide with a
   Vite server you already have running — and starts Vite there with
   `--strictPort`.
3. Installs dependencies on first run if `node_modules` is missing, with `npm ci`
   from the committed `web/package-lock.json`. If that fails it stops with an
   error and does not fall back to `npm install` (see the notes below).
4. Opens a browser window to `http://localhost:<port>/` once the server responds.
5. Leaves the server running in that terminal. **Ctrl-C** there stops it.

## Notes and caveats

- **Use Node.js 22 or later**, as [SETUP.md](../../SETUP.md#nodejs-python3-and-docker)
  says (the AWS CDK needs it). If `node` can't be found, the runner prints a
  "node not found" message and waits for a keypress before closing.
- **If the first-run install fails, the launcher stops.** `npm ci` installs
  exactly the versions in `web/package-lock.json` and fails if they disagree
  with `package.json`. With a missing or stale lockfile, `npm install` would
  resolve version ranges from the registry at that moment and rewrite the
  lockfile, so the launcher never falls back to it. The usual causes are no route to the npm registry, a
  Node.js or npm that is too old, or a missing or out-of-date lockfile. Fix that
  and launch again; the launcher removes the empty `node_modules` that a failed
  `npm ci` leaves, so the next launch retries the install. The manual steps are
  in [SETUP.md](../../SETUP.md) step 5.
- **The shortcut is machine-specific and is not committed.** It embeds the
  absolute path of this repo so it keeps working from the Desktop. If you move
  the repo, re-run `npm run create-shortcut`.
- **macOS first launch:** the app is unsigned, so the first time, right-click the
  icon → **Open** → **Open** to get past Gatekeeper. macOS may also prompt once
  to allow it to control Terminal/Chrome — click OK.
- **Browser choice (macOS):** it opens a new **Chrome** window if Chrome is
  installed (driven via AppleScript, which reliably reaches an already-running
  Chrome), otherwise your default browser. Windows/Linux use the default browser.
- **The dashboard still needs its config.** The launcher only starts the server;
  set `VITE_API_URL` / `VITE_API_KEY` in `web/.env` (or the app's Settings tab)
  per [SETUP.md](../../SETUP.md) step 5, or the console loads but can't reach the
  backend.
- **Windows is best-effort.** The scripts are correct but are exercised less than
  the macOS path. If the `.lnk` misbehaves, you can always run
  `scripts\launcher\run-dev.bat` directly.

## Files

| File | Purpose |
|---|---|
| `create-shortcut.mjs` | OS-detecting dispatcher (`npm run create-shortcut`). |
| `run-dev.sh` | macOS/Linux runner: pick free port, start Vite, open browser. |
| `run-dev.bat` | Windows runner (same behavior). |
| `make-desktop-shortcut.sh` | macOS generator: builds the `.app` on the Desktop. |
| `make-desktop-shortcut.ps1` | Windows generator: writes the Desktop `.lnk`. |

## Environment overrides

Both runners honor: `REPO_ROOT` (override repo autodetect), `PORT_MIN` /
`PORT_MAX` (default `5173`/`5183`), and `NO_BROWSER=1` (start the server without
opening a browser).
