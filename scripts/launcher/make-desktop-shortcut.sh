#!/bin/bash
#
# Create a double-click Desktop launcher (macOS) for the demo dashboard.
#
# The demo ships a four-brand catalog in content/brand.md; this launcher is a
# local dev convenience, so it resolves the DEFAULT brand (defaultBrand in the
# frontmatter) and uses that brand's name, accent color and per-brand logo
# (media/<id>/logo.png) for the shortcut label and icon.
#
# Builds a small .app bundle on your Desktop whose icon comes from your brand
# (media/logo.png on the brand accent color) and whose only job is to run
# scripts/launcher/run-dev.sh from THIS repo — start Vite on a free port and
# open a browser window to it.
#
# The generated .app is machine-specific (it embeds this repo's path) and is
# NOT committed. Re-run this script if you move the repo.
#
# Usage:
#   scripts/launcher/make-desktop-shortcut.sh
#   DEST_DIR=~/Applications scripts/launcher/make-desktop-shortcut.sh   # put it elsewhere

set -euo pipefail

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This generator is for macOS. On Windows use make-desktop-shortcut.ps1."
  exit 1
fi

# --- Locate the repo from this script's location ---------------------------
SCRIPT_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUNNER="$REPO_ROOT/scripts/launcher/run-dev.sh"
BRAND_MD="$REPO_ROOT/content/brand.md"

[ -f "$RUNNER" ] || { echo "ERROR: runner not found at $RUNNER"; exit 1; }
chmod +x "$RUNNER"

# --- Resolve the default brand from the content/brand.md catalog -----------
# brand.md holds a four-brand catalog: a top-level `defaultBrand` scalar and a
# `brands:` map keyed by id, each block indented beneath it. This launcher does
# not know which brand was deployed, so it uses the default brand's identity for
# the shortcut label and icon. Nothing is hardcoded: the values come from the
# resolved block, with last-resort fallbacks only if the file cannot be read.

# A top-level scalar (e.g. `defaultBrand: "anyhealth"`), stripped of quotes/comments.
read_top_scalar() {
  grep -E "^[[:space:]]*$1:" "$BRAND_MD" 2>/dev/null | head -1 \
    | sed -E "s/^[[:space:]]*$1:[[:space:]]*//; s/[[:space:]]*#.*$//; s/^\"//; s/\"[[:space:]]*$//; s/^'//; s/'[[:space:]]*$//"
}

# A sub-key of one brand's block: scan from the `  <id>:` line to the next
# sibling (a line indented by the same two spaces), and read `    <key>:`.
read_brand_key() {
  local brand="$1" key="$2"
  awk -v brand="$brand" -v key="$key" '
    $0 ~ ("^  " brand ":[[:space:]]*$") { inblk=1; next }
    inblk {
      if ($0 ~ /^  [A-Za-z_]/ && $0 !~ /^    /) { exit }
      if ($0 ~ ("^    " key ":")) {
        line=$0
        sub(("^    " key ":[[:space:]]*"), "", line)
        # A quoted value may legitimately contain "#" (e.g. a hex color), so
        # take the quoted span verbatim when present; otherwise the value is a
        # bare token and a trailing " # comment" is stripped.
        if (line ~ /^"[^"]*"/) { sub(/^"/, "", line); sub(/".*$/, "", line) }
        else if (line ~ /^'"'"'[^'"'"']*'"'"'/) { sub(/^'"'"'/, "", line); sub(/'"'"'.*$/, "", line) }
        else { sub(/[[:space:]]+#.*$/, "", line); sub(/[[:space:]]+$/, "", line) }
        print line; exit
      }
    }
  ' "$BRAND_MD" 2>/dev/null
}

DEFAULT_BRAND="$(read_top_scalar defaultBrand)"
[ -z "$DEFAULT_BRAND" ] && DEFAULT_BRAND="anyhealth"

BRAND_NAME="$(read_brand_key "$DEFAULT_BRAND" brandName)"
[ -z "$BRAND_NAME" ] && BRAND_NAME="AnyHealth"
ACCENT="$(read_brand_key "$DEFAULT_BRAND" accentColor)"
[ -z "$ACCENT" ] && ACCENT="#0B6E6F"
LOGO_REL="$(read_brand_key "$DEFAULT_BRAND" logoImage)"
[ -z "$LOGO_REL" ] && LOGO_REL="media/$DEFAULT_BRAND/logo.png"
LOGO="$REPO_ROOT/$LOGO_REL"

APP_NAME="$BRAND_NAME Dashboard"
DEST_DIR="${DEST_DIR:-$HOME/Desktop}"
APP="$DEST_DIR/$APP_NAME.app"

echo "Repo:   $REPO_ROOT"
echo "Brand:  $BRAND_NAME (accent $ACCENT)"
echo "Target: $APP"

# --- Build the bundle skeleton ---------------------------------------------
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# Info.plist
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>$APP_NAME</string>
    <key>CFBundleDisplayName</key>
    <string>$APP_NAME</string>
    <key>CFBundleIdentifier</key>
    <string>com.rcsdemo.dashboard.launcher</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>launch</string>
    <key>CFBundleIconFile</key>
    <string>icon</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

# Launcher executable: opens Terminal running the repo's run-dev.sh.
# REPO_ROOT is embedded so the app keeps working from the Desktop. We pass the
# runner path to osascript as an ARGUMENT (quoted form of) so spaces/quotes in
# the path can't break the AppleScript parse.
cat > "$APP/Contents/MacOS/launch" <<LAUNCH
#!/bin/bash
RUNNER="$RUNNER"
osascript \\
  -e 'on run argv' \\
  -e '  tell application "Terminal"' \\
  -e '    activate' \\
  -e '    do script "clear; " & quoted form of (item 1 of argv) & "; exit"' \\
  -e '  end tell' \\
  -e 'end run' \\
  "\$RUNNER"
LAUNCH
chmod +x "$APP/Contents/MacOS/launch"

# --- Generate the icon from the logo on the accent color -------------------
make_icon() {
  local out="$APP/Contents/Resources/icon.icns"
  if [ ! -f "$LOGO" ]; then
    echo "note: $LOGO missing — app will use the default icon."
    return
  fi
  if ! command -v iconutil >/dev/null 2>&1; then
    echo "note: iconutil unavailable — skipping custom icon."
    return
  fi
  # Find a python interpreter that actually has Pillow. `python3` under bash is
  # often a bare interpreter without Pillow even when a versioned one (e.g.
  # python3.12) has it, so probe a few candidates rather than trusting `python3`.
  PY_WITH_PIL=""
  for cand in "${PYTHON:-}" python3 python3.13 python3.12 python3.11 python3.10 python3.9; do
    [ -z "$cand" ] && continue
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import PIL" 2>/dev/null; then
      PY_WITH_PIL="$cand"; break
    fi
  done

  if [ -n "$PY_WITH_PIL" ]; then
    ACCENT_HEX="$ACCENT" LOGO_PATH="$LOGO" ICNS_OUT="$out" "$PY_WITH_PIL" - <<'PY'
import os, tempfile, subprocess
from PIL import Image, ImageDraw
hexv = os.environ["ACCENT_HEX"].lstrip("#")
accent = tuple(int(hexv[i:i+2], 16) for i in (0, 2, 4)) + (255,)
S = 1024
bg = Image.new("RGBA", (S, S), (0, 0, 0, 0))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S-1, S-1], radius=int(S*0.2237), fill=255)
bg = Image.composite(Image.new("RGBA", (S, S), accent), bg, mask)
logo = Image.open(os.environ["LOGO_PATH"]).convert("RGBA")
t = int(S*0.62); logo = logo.resize((t, t), Image.LANCZOS)
off = (S-t)//2; bg.alpha_composite(logo, (off, off))
iconset = tempfile.mkdtemp(suffix=".iconset")
for base, scale in [(16,1),(16,2),(32,1),(32,2),(128,1),(128,2),(256,1),(256,2),(512,1),(512,2)]:
    px = base*scale
    name = f"icon_{base}x{base}{'@2x' if scale==2 else ''}.png"
    bg.resize((px, px), Image.LANCZOS).save(os.path.join(iconset, name))
subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.environ["ICNS_OUT"]], check=True)
PY
    echo "icon: generated from logo + accent color."
  else
    # Fallback: use the logo as-is (square), no accent background.
    local iconset; iconset="$(mktemp -d)/icon.iconset"; mkdir -p "$iconset"
    for sz in 16 32 128 256 512; do
      sips -z "$sz" "$sz" "$LOGO" --out "$iconset/icon_${sz}x${sz}.png" >/dev/null 2>&1
      sips -z "$((sz*2))" "$((sz*2))" "$LOGO" --out "$iconset/icon_${sz}x${sz}@2x.png" >/dev/null 2>&1
    done
    iconutil -c icns "$iconset" -o "$out" 2>/dev/null && echo "icon: generated from logo (Pillow not installed; no accent background)." \
      || echo "note: icon generation failed — using default icon."
  fi
}
make_icon

# --- Register with LaunchServices so Finder shows it correctly -------------
touch "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" >/dev/null 2>&1 || true

echo ""
echo "Done. '$APP_NAME' is on your Desktop."
echo "Double-click it to start the dashboard. First launch: right-click → Open"
echo "to get past Gatekeeper (the app is unsigned)."
