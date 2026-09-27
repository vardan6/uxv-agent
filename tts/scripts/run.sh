#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
PYTHON_BIN="$ROOT/.venv/bin/python"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Shared venv not found at $ROOT/.venv"
  echo "Create it from the repository root:"
  echo "  python3 -m venv .venv"
  echo "  .venv/bin/python -m pip install -r tts/requirements.txt"
  exit 1
fi

cd "$ROOT"
exec "$PYTHON_BIN" -m uvicorn tts.app:app --host "${UXV_TTS_HOST:-127.0.0.1}" --port "${UXV_TTS_PORT:-9101}"
