@echo off
setlocal
if exist "%~dp0chromium-forge\dist\luminara-browser-win64\Launch-luminara-browser.cmd" (
  call "%~dp0chromium-forge\dist\luminara-browser-win64\Launch-luminara-browser.cmd" %*
  exit /b %ERRORLEVEL%
)
for /d %%D in ("%~dp0chromium-forge\dist\*-win64") do (
  for %%F in ("%%~fD\Launch-*.cmd") do (
    call "%%~fF" %*
    exit /b %ERRORLEVEL%
  )
)
echo [Luminara Browser] Portable bundle not yet unpacked.
echo Run "cd chromium-forge && python -m forge build-portable" (or download the GitHub Release portable zip) first.
pause
exit /b 1
