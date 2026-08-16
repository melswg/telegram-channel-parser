@echo off
setlocal
cd /d "%~dp0"
set "TELEGRAM_IMPORTER_DEMO=1"

if not exist ".venv\Scripts\python.exe" (
  echo Приложение ещё не установлено. Сначала запустите Start.bat.
  pause
  exit /b 1
)

start "" powershell.exe -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8000'"
".venv\Scripts\python.exe" -m app.web

if errorlevel 1 pause
