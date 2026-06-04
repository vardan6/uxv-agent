#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
PYTHON_BIN="$ROOT/.venv/bin/python"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Shared venv not found at $ROOT/.venv"
  echo "Create it from the repository root:"
  echo "  python3 -m venv .venv"
  echo "  .venv/bin/python -m pip install -r gcs_server/requirements-gcs.txt"
  exit 1
fi

cd "$DIR"
exec "$PYTHON_BIN" ./app.py
