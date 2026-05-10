#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$DIR/.venv/bin/python"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "TTS venv not found at $DIR/.venv"
  echo "Create it from this directory:"
  echo "  python -m venv .venv"
  echo "  source .venv/bin/activate"
  echo "  pip install -r requirements.txt"
  exit 1
fi

cd "$DIR"
exec "$PYTHON_BIN" -m uvicorn \
  --app-dir "$DIR/.." \
  tts_service.app:app \
  --host "${REMOTE_ROVER_TTS_HOST:-127.0.0.1}" \
  --port "${REMOTE_ROVER_TTS_PORT:-9101}"
