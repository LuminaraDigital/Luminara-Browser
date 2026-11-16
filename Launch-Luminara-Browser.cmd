@echo off
setlocal
for /d %%D in ("%~dp0chromium-forge\dist\*-win64") do (
  for %%F in ("%%~fD\Launch-*.cmd") do (
    call "%%~fF" %*
    exit /b %ERRORLEVEL%
  )
)
echo [Luminara Browser] Portable bundle not yet unpacked.
echo Run Launch-Forge-Studio.cmd and click "3. Build Portable Win64" first.
pause
exit /b 1
