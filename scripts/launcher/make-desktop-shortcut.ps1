<#
.SYNOPSIS
  Create a double-click Desktop launcher (Windows) for the demo dashboard.

.DESCRIPTION
  Writes a Desktop shortcut (.lnk) that runs scripts\launcher\run-dev.bat from
  THIS repo: start Vite on a free port and open the default browser to it.
  Uses media\logo.png as the shortcut icon when it can build a .ico.

  The shortcut is machine-specific (it points at this repo's path) and is not
  committed. Re-run this script if you move the repo.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\launcher\make-desktop-shortcut.ps1

.PARAMETER DestDir
  Where to put the shortcut. Defaults to the Desktop.
#>
[CmdletBinding()]
param(
  [string]$DestDir = [Environment]::GetFolderPath('Desktop')
)

$ErrorActionPreference = 'Stop'

# --- Locate the repo from this script's location ---------------------------
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = (Resolve-Path (Join-Path $ScriptDir '..\..')).Path
$Runner    = Join-Path $RepoRoot 'scripts\launcher\run-dev.bat'
$BrandMd   = Join-Path $RepoRoot 'content\brand.md'

if (-not (Test-Path $Runner)) { throw "Runner not found at $Runner" }

# --- Resolve the default brand from the content\brand.md catalog -----------
# brand.md holds a four-brand catalog: a top-level `defaultBrand` scalar and a
# `brands:` map keyed by id. This launcher does not know which brand was
# deployed, so it uses the default brand's identity (name, accent, per-brand
# logo) for the shortcut. Nothing is hardcoded; the "AnyHealth" fallback is
# last-resort only, if the file cannot be read.

# A top-level scalar such as `defaultBrand: "anyhealth"`.
function Get-TopScalar([string]$key) {
  if (-not (Test-Path $BrandMd)) { return $null }
  $line = Select-String -Path $BrandMd -Pattern "^\s*$key\s*:" | Select-Object -First 1
  if (-not $line) { return $null }
  $v = $line.Line -replace "^\s*$key\s*:\s*", '' -replace '\s*#.*$', ''
  return $v.Trim().Trim('"').Trim("'")
}

# A sub-key of one brand's block: walk from the `  <id>:` line to the next
# 2-space-indented sibling, reading `    <key>:`. A quoted value may contain
# "#" (a hex color), so a quoted span is taken verbatim; a bare value has any
# trailing " # comment" stripped.
function Get-BrandKey([string]$brand, [string]$key) {
  if (-not (Test-Path $BrandMd)) { return $null }
  $inBlk = $false
  foreach ($raw in Get-Content -LiteralPath $BrandMd) {
    if ($raw -match ("^  " + [regex]::Escape($brand) + ":\s*$")) { $inBlk = $true; continue }
    if ($inBlk) {
      if ($raw -match '^  [A-Za-z_]' -and $raw -notmatch '^    ') { break }
      if ($raw -match ("^    " + [regex]::Escape($key) + ":\s*(.*)$")) {
        $v = $Matches[1]
        if ($v -match '^"([^"]*)"') { return $Matches[1] }
        elseif ($v -match "^'([^']*)'") { return $Matches[1] }
        else { return ($v -replace '\s+#.*$', '').Trim() }
      }
    }
  }
  return $null
}

$DefaultBrand = Get-TopScalar 'defaultBrand'
if ([string]::IsNullOrWhiteSpace($DefaultBrand)) { $DefaultBrand = 'anyhealth' }

$BrandName = Get-BrandKey $DefaultBrand 'brandName'
if ([string]::IsNullOrWhiteSpace($BrandName)) { $BrandName = 'AnyHealth' }
$AppName = "$BrandName Dashboard"

$LogoRel = Get-BrandKey $DefaultBrand 'logoImage'
if ([string]::IsNullOrWhiteSpace($LogoRel)) { $LogoRel = "media/$DefaultBrand/logo.png" }
$Logo = Join-Path $RepoRoot ($LogoRel -replace '/', '\')

Write-Host "Repo:   $RepoRoot"
Write-Host "Brand:  $BrandName"

# --- Build an .ico from the logo (best-effort) -----------------------------
$IconPath = $null
if (Test-Path $Logo) {
  try {
    Add-Type -AssemblyName System.Drawing
    $icoDir = Join-Path $RepoRoot '.deploy'
    New-Item -ItemType Directory -Force -Path $icoDir | Out-Null
    $IconPath = Join-Path $icoDir 'dashboard-icon.ico'

    $src = [System.Drawing.Image]::FromFile($Logo)
    # Draw the logo centered on a 256x256 transparent canvas.
    $bmp = New-Object System.Drawing.Bitmap 256, 256
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g.Clear([System.Drawing.Color]::Transparent)
    $g.DrawImage($src, 0, 0, 256, 256)
    $g.Dispose(); $src.Dispose()

    $hicon = $bmp.GetHicon()
    $icon  = [System.Drawing.Icon]::FromHandle($hicon)
    $fs = [System.IO.File]::Open($IconPath, [System.IO.FileMode]::Create)
    $icon.Save($fs); $fs.Close()
    $icon.Dispose(); $bmp.Dispose()
    Write-Host "icon: generated from logo -> $IconPath"
  } catch {
    Write-Warning "Could not build icon from logo ($($_.Exception.Message)); using default."
    $IconPath = $null
  }
}

# --- Create the Desktop shortcut -------------------------------------------
$LnkPath = Join-Path $DestDir "$AppName.lnk"
$wsh = New-Object -ComObject WScript.Shell
$sc  = $wsh.CreateShortcut($LnkPath)
# Run the .bat in its own console window so the dev URL and Ctrl-C work.
$sc.TargetPath       = "$env:ComSpec"          # cmd.exe
$sc.Arguments        = "/c `"`"$Runner`"`""
$sc.WorkingDirectory = Split-Path -Parent $Runner
$sc.Description      = "$AppName - start the local Vite dashboard"
if ($IconPath) { $sc.IconLocation = "$IconPath,0" }
$sc.Save()

Write-Host ""
Write-Host "Done. '$AppName' is on your Desktop."
Write-Host "Double-click it to start the dashboard."
