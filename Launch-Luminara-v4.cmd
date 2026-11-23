@echo off
setlocal
set "ELECTRON_RUN_AS_NODE="
set "SHELL_DIR=%~dp0luminara-shell"
set "FORCE_REBUILD=0"

if /i "%~1"=="--rebuild" (
  set "FORCE_REBUILD=1"
  shift
)

if not exist "%SHELL_DIR%\package.json" (
  echo [Luminara Browser v4] Missing luminara-shell directory at "%SHELL_DIR%".
  pause
  exit /b 1
)

pushd "%SHELL_DIR%"

if not exist "node_modules\electron\dist\electron.exe" (
  echo [Luminara Browser v4] Installing desktop shell dependencies...
  call npm install
  if errorlevel 1 (
    popd
    pause
    exit /b 1
  )
)

set "NEEDS_BUILD=%FORCE_REBUILD%"
if not exist "dist\main\index.js" set "NEEDS_BUILD=1"
if not exist "dist\main\shell-preload.js" set "NEEDS_BUILD=1"
if not exist "dist\main\web-preload.js" set "NEEDS_BUILD=1"
if not exist "dist\renderer\index.html" set "NEEDS_BUILD=1"

if "%NEEDS_BUILD%"=="1" (
  echo [Luminara Browser v4] Building native desktop shell and renderer...
  call npm run build
  if errorlevel 1 (
    popd
    pause
    exit /b 1
  )
)

start "" "%SHELL_DIR%\node_modules\electron\dist\electron.exe" "%SHELL_DIR%" %1 %2 %3 %4 %5 %6 %7 %8 %9
popd
exit /b 0
