@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0chromium-forge"
start "" powershell -NoProfile -WindowStyle Hidden -Command "for ($i=0; $i -lt 30; $i++) { if (Get-NetTCPConnection -LocalPort 8795 -State Listen -ErrorAction SilentlyContinue) { Start-Process 'http://127.0.0.1:8795'; break }; Start-Sleep -Milliseconds 150 }"
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -m forge studio --host 127.0.0.1 --port 8795
) else (
  python -m forge studio --host 127.0.0.1 --port 8795
)
if errorlevel 1 pause
