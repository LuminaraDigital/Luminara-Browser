@echo off
setlocal
if exist "%~dp0chromium-forge\dist\luminara-browser-win64\LuminaraBrowser.exe" (
  start "" "%~dp0chromium-forge\dist\luminara-browser-win64\LuminaraBrowser.exe" %*
  exit /b 0
)
if exist "%~dp0chromium-forge\dist\luminara-browser-win64\Launch-luminara-browser.cmd" (
  call "%~dp0chromium-forge\dist\luminara-browser-win64\Launch-luminara-browser.cmd" %*
  exit /b %ERRORLEVEL%
)
for /d %%D in ("%~dp0chromium-forge\dist\*-win64") do (
  if exist "%%~fD\LuminaraBrowser.exe" (
    start "" "%%~fD\LuminaraBrowser.exe" %*
    exit /b 0
  )
  for %%F in ("%%~fD\Launch-*.cmd") do (
    call "%%~fF" %*
    exit /b %ERRORLEVEL%
  )
)
echo [Luminara Browser] Portable bundle not yet unpacked.
echo Run "cd chromium-forge && python -m forge build-portable" (or download the GitHub Release portable zip) first.
pause
exit /b 1
