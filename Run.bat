@echo off
rem Mu (mu-companion) one-click launcher for Windows.
rem Mirrors PawzoChat's Run.bat: detect python -> create venv -> install deps -> start.
setlocal
cd /d "%~dp0"
title Mu

set PY=.venv\Scripts\python.exe

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo  [Mu] Python not found.
  echo  Please install Python 3.11+ from https://www.python.org/downloads/
  echo  ^(check "Add python.exe to PATH" during install^), then run this again.
  echo.
  pause
  exit /b 1
)

if not exist "%PY%" (
  echo  [Mu] First run: creating virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo  [Mu] Failed to create .venv. Check disk space / permissions.
    pause
    exit /b 1
  )
)

if not exist ".venv\.deps_ok" (
  echo  [Mu] Installing dependencies - first run only, may take a few minutes...
  "%PY%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo  [Mu] pip install failed. Check your network or proxy, then run again.
    pause
    exit /b 1
  )
  type nul > ".venv\.deps_ok"
  echo  [Mu] Dependencies installed.
)

echo  [Mu] Environment self-check...
"%PY%" main.py doctor
if errorlevel 1 (
  echo  [Mu] Doctor found blocking issues, see above.
  pause
  exit /b 1
)

echo  [Mu] Starting Mu - browser will open http://127.0.0.1:8000 in a few seconds
start "" cmd /c "timeout /t 5 /nobreak >nul & start http://127.0.0.1:8000"
"%PY%" main.py web

echo.
echo  [Mu] Server stopped.
pause
