@echo off
setlocal enabledelayedexpansion
rem ---------------------------------------------------------------------------
rem AnyHealth local dashboard launcher (Windows).
rem Starts the Vite dev server for web\ on the first free port and opens the
rem default browser to it. Path-independent: locates the repo from this file.
rem
rem Env overrides: REPO_ROOT, PORT_MIN (default 5173), PORT_MAX (default 5183),
rem                NO_BROWSER=1 to skip opening a browser.
rem ---------------------------------------------------------------------------

rem This script lives at <repo>\scripts\launcher\run-dev.bat.
if "%REPO_ROOT%"=="" (
  pushd "%~dp0\..\.." >nul
  set "REPO_ROOT=!CD!"
  popd >nul
)
set "WEB_DIR=%REPO_ROOT%\web"
if "%PORT_MIN%"=="" set "PORT_MIN=5173"
if "%PORT_MAX%"=="" set "PORT_MAX=5183"

where node >nul 2>nul
if errorlevel 1 (
  echo ERROR: node not found. Install Node.js 22 or later ^(24 LTS recommended^) from https://nodejs.org
  pause
  exit /b 1
)
if not exist "%WEB_DIR%" (
  echo ERROR: web\ not found under "%REPO_ROOT%".
  pause
  exit /b 1
)

cd /d "%WEB_DIR%"

rem --- Pick the first free port using node (no external tools needed) --------
set "PORT="
for /f "usebackq delims=" %%p in (`node -e "const net=require('net');const min=%PORT_MIN%,max=%PORT_MAX%;function freeOn(p,h){return new Promise(r=>{const s=net.createServer();s.once('error',e=>r(e.code!=='EADDRINUSE'));s.once('listening',()=>s.close(()=>r(true)));s.listen(p,h);});}async function free(p){return (await freeOn(p,'127.0.0.1'))&&(await freeOn(p,'::1'));}(async()=>{for(let p=min;p<=max;p++){if(await free(p)){process.stdout.write(String(p));return;}}process.exit(3);})();"`) do set "PORT=%%p"

if "%PORT%"=="" (
  echo ERROR: No free port between %PORT_MIN% and %PORT_MAX%. Close another dev server and retry.
  pause
  exit /b 1
)
set "URL=http://localhost:%PORT%/"

rem --- Install deps on first run ----------------------------------------------
rem npm ci installs exactly what web\package-lock.json pins, and fails if that
rem disagrees with package.json. There is no "npm install" fallback on purpose:
rem with a missing or stale lockfile it resolves version ranges from the
rem registry at that moment and rewrites the lockfile, so a failure is reported
rem rather than worked around. npm ci empties node_modules before it installs,
rem so a failed run is followed by rmdir: an empty folder left behind would be
rem taken for a finished install on the next launch.
if not exist "node_modules" (
  echo Installing dependencies ^(first run^)...
  call npm ci
  if errorlevel 1 (
    if exist "node_modules" rmdir /s /q "node_modules"
    echo.
    echo ERROR: npm ci failed in web\, so the dashboard's dependencies are not installed.
    echo It installs exactly the versions pinned in web\package-lock.json and does not fall
    echo back to "npm install". The usual causes are:
    echo   - no route to the npm registry: check your network, proxy or VPN
    echo   - a Node.js or npm that is too old: this repo needs Node.js 22 or later, see "node --version"
    echo   - web\package-lock.json missing, or out of step with web\package.json
    echo Fix that and launch again. SETUP.md, step 5 "Run the dashboard", has the manual steps.
    pause
    exit /b 1
  )
)

rem --- Open the browser shortly after Vite starts (background) ---------------
if not "%NO_BROWSER%"=="1" (
  start "" /b cmd /c "timeout /t 4 >nul & start "" "%URL%""
)

echo AnyHealth dashboard starting on %URL%
echo Press Ctrl-C to stop.
echo.

call npm run dev -- --port %PORT% --strictPort
endlocal
