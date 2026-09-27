#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
PYTHON_BIN="$ROOT/.venv/bin/python"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Shared venv not found at $ROOT/.venv"
  echo "Create it from the repository root:"
  echo "  python3 -m venv .venv"
  echo "  .venv/bin/python -m pip install -r mav-sim/requirements.txt"
  exit 1
fi

cd "$DIR"
echo "[mav-sim] Starting — web UI http://localhost:9010  MAVLink UDP :14550"
exec "$PYTHON_BIN" app.py
