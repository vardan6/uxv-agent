#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
PYTHON_BIN="$DIR/.venv/bin/python"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "TTS venv not found at $DIR/.venv"
  echo "Create it from the repository root:"
  echo "  python -m venv tts_service/.venv"
  echo "  source tts_service/.venv/bin/activate"
  echo "  pip install -r tts_service/requirements.txt"
  exit 1
fi

cd "$ROOT"
exec "$PYTHON_BIN" -m uvicorn tts_service.app:app --host "${REMOTE_ROVER_TTS_HOST:-127.0.0.1}" --port "${REMOTE_ROVER_TTS_PORT:-9101}"
