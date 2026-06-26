#!/usr/bin/env bash
#
# run-app.sh — one-shot launcher for the GCS operator console (manual testing).
#
# Starts the GCS backend (gcs_server/, root .venv) together with the greenfield
# Vite + React frontend (frontend/). This is the GCS-only counterpart to run.sh,
# which starts the backend alone.
#
# Modes:
#   (default) dev   Backend + Vite dev server with hot reload. Open the Vite URL.
#   --prod          Build the frontend, then the backend serves it under /app.
#
# Ctrl-C stops both processes. The MQTT broker is configured remotely in
# config/common.local.json, so no local broker is started here.
#
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
PY="$ROOT/.venv/bin/python"
CONFIG="$ROOT/config/common.local.json"
FRONTEND="$ROOT/frontend"

MODE="dev"
for arg in "$@"; do
  case "$arg" in
    --prod) MODE="prod" ;;
    --dev)  MODE="dev" ;;
    -h|--help)
      sed -n '3,14p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

# --- preflight ---------------------------------------------------------------
if [ ! -x "$PY" ]; then
  echo "Backend venv not found at $ROOT/.venv" >&2
  echo "Create it from the repository root:" >&2
  echo "  python3 -m venv .venv" >&2
  echo "  .venv/bin/python -m pip install -r gcs_server/requirements-gcs.txt" >&2
  exit 1
fi
[ -f "$CONFIG" ] || { echo "Config not found: $CONFIG" >&2; exit 1; }

# Read GCS host/port from config so the dev proxy and printed URLs always match.
read -r GCS_HOST GCS_PORT < <(
  "$PY" -c "import json;d=json.load(open('$CONFIG'))['gcs'];print(d['host'],d['port'])"
)
DEV_TARGET="http://${GCS_HOST}:${GCS_PORT}"

# --- process management ------------------------------------------------------
PIDS=()
start() {  # start <label> <command...> in its own process group
  echo ">> starting $1"; shift
  setsid "$@" &
  PIDS+=("$!")
}
wait_for_backend() {
  echo ">> waiting for GCS backend health at ${DEV_TARGET}/api/health"
  if ! "$PY" - <<'PY' "$GCS_HOST" "$GCS_PORT"; then
import http.client
import sys
import time

host = sys.argv[1]
port = int(sys.argv[2])
deadline = time.time() + 30.0
last_error = "timeout"

while time.time() < deadline:
    try:
        conn = http.client.HTTPConnection(host, port, timeout=1.0)
        conn.request("GET", "/api/health")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        if 200 <= resp.status < 300:
            raise SystemExit(0)
        last_error = f"HTTP {resp.status}"
    except Exception as exc:
        last_error = str(exc)
    time.sleep(0.25)

print(f"GCS backend did not become ready within 30s: {last_error}", file=sys.stderr)
raise SystemExit(1)
PY
    echo "Backend failed to start cleanly." >&2
    exit 1
  fi
}
cleanup() {
  echo ""; echo ">> shutting down..."
  for pid in "${PIDS[@]}"; do
    kill -TERM "-${pid}" 2>/dev/null || true   # negative == process group
  done
  wait 2>/dev/null || true
  echo ">> done."
}
trap cleanup INT TERM EXIT

# --- backend -----------------------------------------------------------------
start "GCS backend (${DEV_TARGET})" \
  bash -c "cd '$DIR' && exec '$PY' ./app.py"

# --- frontend ----------------------------------------------------------------
if [ ! -d "$FRONTEND/node_modules" ]; then
  echo ">> installing frontend deps (npm install)"
  ( cd "$FRONTEND" && npm install )
fi

if [ "$MODE" = "prod" ]; then
  echo ">> building frontend (npm run build -> gcs_server/webapp)"
  ( cd "$FRONTEND" && npm run build )
  APP_URL="${DEV_TARGET}/app"
else
  wait_for_backend
  start "Vite dev server" \
    bash -c "cd '$FRONTEND' && GCS_DEV_TARGET='$DEV_TARGET' exec npm run dev"
  APP_URL="http://localhost:5173"
fi

# --- ready -------------------------------------------------------------------
echo ""
echo "=============================================================="
echo " GCS server is starting (mode: $MODE)"
echo " Operator console:  $APP_URL"
echo " Backend API/WS:    $DEV_TARGET"
echo " Press Ctrl-C to stop."
echo "=============================================================="
echo ""

wait -n 2>/dev/null || wait
