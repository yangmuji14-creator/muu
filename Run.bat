@echo off
chcp 65001 >nul
rem Mu (mu-companion) one-click launcher for Windows.
rem Supports two modes:
rem   1. Standalone offline mode (when bundled runtime\python.exe exists): zero install.
rem   2. Source mode: detect python -> create venv -> install deps -> start.
setlocal
cd /d "%~dp0"
title Mu

if not exist "config" mkdir "config" >nul 2>nul
if not exist "config\settings.json" if exist "config\settings.example.json" copy /y "config\settings.example.json" "config\settings.json" >nul
if not exist "config\personas.json" if exist "config\personas.example.json" copy /y "config\personas.example.json" "config\personas.json" >nul
if not exist "config\mcp_servers.json" if exist "config\mcp_servers.example.json" copy /y "config\mcp_servers.example.json" "config\mcp_servers.json" >nul

if exist "runtime\python.exe" (
  set "PY=%~dp0runtime\python.exe"
  set "CYBER_NO_VENV=1"
  set "PYTHONUTF8=1"
  set "PYTHONNOUSERSITE=1"
  set "PYTHONPATH="
  set "PYTHONHOME="
  echo  [Mu] Using bundled Python runtime ^(offline ready^).
  goto :run_doctor
)

set "PY=.venv\Scripts\python.exe"

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

rem Semantic memory: only when the model directory ships alongside (one-click build).
rem sentence-transformers pulls torch (~2 GB) - worth skipping for people who only
rem want keyword memory, so this is gated on the model actually being present.
if exist "models\bge-small-zh-v1.5\config.json" (
  if not exist ".venv\.vector_ok" (
    echo.
    echo  [Mu] Vector memory model found - installing semantic memory support...
    echo  [Mu] This pulls torch, roughly 2 GB and a few minutes. One time only.
    "%PY%" -m pip install -r requirements-vector.txt
    if errorlevel 1 (
      echo  [Mu] Vector deps failed to install. Mu still runs with keyword memory.
      echo  [Mu] Retry later with: "%PY%" -m pip install -r requirements-vector.txt
    ) else (
      type nul > ".venv\.vector_ok"
      echo  [Mu] Semantic memory ready.
    )
  )
)

:run_doctor
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
