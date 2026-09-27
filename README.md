# uxv-agent

uxv-agent is a ground control station (GCS) with an AI agent layer for
uncrewed vehicles (UxV). An operator controls a vehicle directly from the
browser, or asks the agent by text or voice to plan a mission, watch its
execution, and hand control back to a human when something unexpected happens.

It is a working prototype developed against a simulated ground vehicle; the
simulator itself is not part of this repository.

## What is in this repository

| Path | What it is |
|---|---|
| `backend/` | FastAPI GCS server: MQTT bridge, telemetry, replay, video, and the AI agent (`backend/ai/`) |
| `frontend-vanilla/` | Browser operator UI served by the backend |
| `map/` | Map widget shared by the operator UI |
| `mav-sim/` | MAVLink flight-controller simulator used for mission upload and execution tests |
| `rag/` | Retrieval service: ingestion and Qdrant-backed search for the agent |
| `tts/` | Local text-to-speech service (Kokoro) for spoken agent replies |
| `scene/` | Terrain scene manifest and its generate/validate pipeline |
| `config/` | Shared configuration template (`common.example.json`) |
| `tools/`, `bin/` | CLI helpers and the test gates |
| `docs/` | Requirements, design, and architecture decision records |

## Documentation

Start at the [documentation portal](./docs/README.md). Recommended reading order:

1. [Vision](./docs/cross-cutting/vision.md)
2. [Architecture](./docs/cross-cutting/architecture.md)
3. [GCS requirements](./docs/components/gcs/requirements.md)
4. [AI agent requirements](./docs/components/ai-agent/requirements.md) and
   [design](./docs/components/ai-agent/design.md)
5. [Architecture decision records](./docs/cross-cutting/decisions/README.md)
6. [Run and config guide](./docs/cross-cutting/operations/run-and-config.md)

Some docs describe components that live only in the private upstream
repository — the Panda3D simulator (`3d-env/`) and the React operator console
(`frontend/`). They are kept because the decisions they record still shape the
code here.

## Quick start

Requires Python 3.11+, Node.js (for the map tests), and an MQTT broker such as
Mosquitto.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-gcs.txt -r tts/requirements.txt \
            -r mav-sim/requirements.txt -r rag/requirements.txt pytest pytest-cov
cp config/common.example.json config/common.local.json   # then edit hosts/ports
python -m backend
```

Open the GCS at the `gcs.host` / `gcs.port` configured in
`config/common.local.json` (template default `http://127.0.0.1:8080`).
`backend/run.sh` starts the backend from the root `.venv`.

Optional services, each in its own terminal:

```bash
# Text-to-speech (downloads the Kokoro model once)
python tts/scripts/download_kokoro_models.py
python -m uvicorn tts.app:app --host 127.0.0.1 --port 9101

# MAVLink flight-controller simulator (web UI on port 9010)
mav-sim/run.sh
```

Launcher details, shared config behaviour, and telemetry policy are in the
[run and config guide](./docs/cross-cutting/operations/run-and-config.md).

## Tests

```bash
bin/test-fast   # offline, deterministic gate
bin/test-full   # fast gate + coverage + environment-gated smoke checks
```

Both use the root `.venv`. The policy is in
[testing](./docs/cross-cutting/operations/testing.md).

## History

This repository was extracted from a private monorepo with its history kept.
Commits before the 2026-09 restructure use the old names (`gcs_server/`,
`rag_service/`, `tts_service/`, `REMOTE_ROVER_*` environment variables); see
[ADR 0037](./docs/cross-cutting/decisions/0037-project-naming-and-directory-restructure.md)
for the mapping. The UI and some identifiers still say "Remote Rover".

## License

Copyright (C) 2026 vardan6.

Licensed under the GNU Affero General Public License, version 3
(`AGPL-3.0-only`) — see [LICENSE](./LICENSE). If you run a modified version as
a network service, the AGPL requires you to offer its source to that service's
users.
