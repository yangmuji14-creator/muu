#!/bin/bash
# Mu (mu-companion) one-click launcher for macOS.
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo ""
  echo " [Mu] python3 not found. Install Python 3.11+ (https://www.python.org/downloads/)"
  echo "       or 'brew install python', then run this again."
  exit 1
fi

PY=.venv/bin/python

if [ ! -x "$PY" ]; then
  echo " [Mu] First run: creating virtual environment..."
  python3 -m venv .venv || { echo " [Mu] venv creation failed"; exit 1; }
fi

if [ ! -f .venv/.deps_ok ]; then
  echo " [Mu] Installing dependencies - first run only, may take a few minutes..."
  "$PY" -m pip install -r requirements.txt || { echo " [Mu] pip install failed"; exit 1; }
  touch .venv/.deps_ok
fi

echo " [Mu] Environment self-check..."
"$PY" main.py doctor || { echo " [Mu] Doctor found blocking issues, see above."; exit 1; }

echo " [Mu] Starting Mu - open http://127.0.0.1:8000 in a few seconds"
( sleep 5; open http://127.0.0.1:8000 ) &
"$PY" main.py web
