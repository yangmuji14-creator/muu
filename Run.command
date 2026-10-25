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

# Semantic memory: only when the model directory ships alongside (one-click build).
# sentence-transformers pulls torch (~2 GB) - skip it when there is no model to use.
if [ -f "models/bge-small-zh-v1.5/config.json" ] && [ ! -f .venv/.vector_ok ]; then
  echo ""
  echo " [Mu] Vector memory model found - installing semantic memory support..."
  echo " [Mu] This pulls torch, roughly 2 GB and a few minutes. One time only."
  if "$PY" -m pip install -r requirements-vector.txt; then
    touch .venv/.vector_ok
    echo " [Mu] Semantic memory ready."
  else
    echo " [Mu] Vector deps failed to install. Mu still runs with keyword memory."
  fi
fi

echo " [Mu] Environment self-check..."
"$PY" main.py doctor || { echo " [Mu] Doctor found blocking issues, see above."; exit 1; }

echo " [Mu] Starting Mu - open http://127.0.0.1:8000 in a few seconds"
( sleep 5; open http://127.0.0.1:8000 ) &
"$PY" main.py web
