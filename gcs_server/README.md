# Remote Rover GCS

> Note:
> For the current documentation set and high-level project context, start with:
> - `../docs/README.md`
> - `../docs/gcs_server/README.md`
> - `../docs/gcs_server/technical-details.md`

`gcs_server/` is the browser-facing Ground Control Station for the Remote Rover project.

It is a Python FastAPI application with a static frontend. It connects to the same MQTT broker as the simulator, subscribes to rover telemetry and camera topics, publishes control commands, and serves a browser UI for monitoring and manual driving.

## Current Features

- Live telemetry dashboard
- Broker status and topic freshness status
- Config-backed simulator backend identity: `3d-env` or `rover-sim-next`
- Controller lock: one active browser controls, others observe
- Focus-driven browser control activation
- Config-backed keyboard control via arrow keys and `W/A/S/D` defaults
- On-screen control buttons with immediate active-state feedback
- Configurable video pipeline modes
- MQTT camera-frame ingest and WebSocket MJPEG-style browser delivery
- End-to-end simulator POV JPEG publication over MQTT
- Dedicated MQTT setup page (`/setup/mqtt`) for broker/topic/control-rate editing
- Live MQTT reconfiguration via API without restarting the GCS process
- SQLite-backed replay/session logging
- Replay session APIs
- Separate replay page with first Leaflet-based map playback
- Replay scene map loaded from `config/terrain_scene.v1.json`
- Theme controls with persisted mode + light/dark theme variants
- LLM provider settings, provider checks, and purpose-based model routing
- `/ai` provider-backed General Chat with persistent SQLite sessions
- Streaming AI chat responses, retry, archive/restore, purge, session search, and per-session provider override
- AI Chat live current-context injection for rover telemetry, runtime state, settings, LLM provider/routing summaries, scene-map facts, replay summaries, and mission placeholder state

## Current Limitations

- State backend is in-memory only
- No authentication or authorization
- No WebRTC transport yet
- MQTT settings are persisted to local shared config only (no secrets manager)
- Live dashboard map is not implemented yet
- Replay currently covers telemetry, control, runtime events, and camera timing metadata; recorded video playback is not implemented yet
- AI Chat is read-only; the first live current-context layer is implemented, but rover intent parsing, RAG/source controls, web research/search, LangGraph workflows, and rover-agent command workflows are not implemented yet

## Dependencies

Install from the workspace root:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
pip install -r gcs_server/requirements-gcs.txt
```

## Run

From the repository root:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
python -m gcs_server
```

From inside the `gcs_server/` directory:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover/gcs_server
.venv/bin/python app.py
```

Using the helper script inside `gcs_server/`:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover/gcs_server
./run.sh
```

`python -m gcs_server` does not work from inside `gcs_server/` itself because Python needs the parent directory on `sys.path` to resolve the `gcs_server` package.

Default URL:
- `http://localhost:8080`

## Config Source

The GCS currently reads shared settings from:
- `../config/common.local.json` if present
- otherwise `../config/common.example.json`

Main config sections it consumes:

```json
{
  "mqtt": {
    "broker_host": "127.0.0.1",
    "broker_port": 1883,
    "topic_prefix": "/projects/remote-rover",
    "control_topic": "control/manual",
    "state_topic": "telemetry/state",
    "camera_topic": "camera-feed"
  },
  "video": {
    "enabled": true,
    "ingest_mode": "mqtt_frames",
    "delivery_mode": "websocket_mjpeg"
  },
  "gcs": {
    "host": "127.0.0.1",
    "port": 8080,
    "telemetry_stale_ms": 2000
  },
  "simulation": {
    "backend": "3d-env",
    "available_backends": ["3d-env", "rover-sim-next"]
  },
  "logging": {
    "replay_db_path": "data/gcs_replay.sqlite3",
    "ai_sessions_db_path": "data/gcs_ai_sessions.sqlite3"
  },
  "llm_providers": [],
  "model_routing": {}
}
```

## Runtime Structure

Main modules:

- `app.py`: FastAPI app, HTTP routes, WebSocket endpoint, lifespan wiring
- `runtime.py`: runtime assembly for services
- `scene_map.py`: replay scene-map payload from the shared terrain manifest
- `mqtt_service.py`: MQTT connect/subscribe/publish logic
- `control.py`: control loop and held-button publishing
- `state.py`: local in-memory runtime state and freshness tracking
- `replay_store.py`: SQLite session logging and replay data access
- `telemetry.py`: normalized telemetry shaping for replay and UI consistency
- `ws.py`: WebSocket connection manager
- `video.py`: MQTT camera frame decoding helper
- `ai/provider_registry.py`: configured provider to LangChain model adapter
- `ai/context_service.py`: live rover/runtime/settings/LLM/map/replay current-context providers for AI Chat
- `ai/chat_service.py`: read-only General Chat orchestration
- `ai/session_store.py`: SQLite AI session and message storage
- `ai/secret_store.py`: local stored-secret helper
- `static/`: browser UI assets
  - `index.html` + `app.js`: dashboard UI
  - `mqtt-setup.html` + `mqtt-setup.js`: MQTT setup/config UI
  - `replay.html` + `replay.js`: replay page and playback UI
  - `ai.html` + `ai.js`: AI Chat sessions UI

## Browser Control Flow

1. Browser opens `/ws`
2. GCS sends initial runtime snapshot
3. Focused and visible browser dashboard becomes the active controller
4. Browser sends control button states over WebSocket while it remains the active controller
5. GCS publishes digital control frames to MQTT at `control_hz`
6. Browser blur or hidden state clears inputs and deactivates browser control
7. Telemetry is normalized and persisted for replay
8. Telemetry and camera frames received from MQTT are broadcast to connected browsers

## Control Regression Notes

See [docs/gcs_server/regressions.md](../docs/gcs_server/regressions.md) for pinned one-line control invariants that should not regress.

## MQTT Setup Flow

1. Browser opens `/setup/mqtt`
2. GCS returns current MQTT config from shared settings file (`/api/mqtt-config`)
3. User edits host/port/topics/control rate and saves
4. User can also select the active simulator backend identity
5. GCS writes updated shared config and reconnects MQTT runtime immediately
6. Dashboard broker status updates via WebSocket broadcast

## Replay Model

Implemented now:
- GCS records sessions to SQLite
- telemetry, control frames, runtime events, and camera timing metadata are recorded
- `/api/replay/sessions` lists sessions
- `/api/replay/sessions/{session_id}` returns session timeline detail
- `/replay` provides the first playback UI

Not implemented yet:
- recorded video playback
- simulator-origin log import path
- live dashboard map sharing the same playback/live model

## AI Chat Model

Implemented now:
- `/ai` provides read-only General Chat for configured providers
- AI sessions and messages persist to SQLite
- chat calls go through the project LangChain provider adapter layer
- OpenAI-compatible providers and Ollama are supported by the current runtime adapter
- the active provider can come from General Chat routing or a per-session provider override
- streaming send/retry flows are implemented
- each AI send/retry call receives compact live context after the system prompt
- assistant messages store current context snapshots and provider names in `ai_messages.meta_json`
- current rover state, runtime state, saved settings, LLM provider/routing summaries, scene-map summary, object lookup, replay summary, recent telemetry, and no-active-mission state are available to chat
- settings and LLM context are structured current facts, not RAG documents
- larger map/object/replay/perception details should be retrieved on demand through tools rather than injected into every chat prompt
- sensitive LLM secrets are redacted; AI Chat receives safe auth summaries only, not raw API keys or stored secret values

Not implemented yet:
- RAG source controls and document upload
- web research/search as a chat source
- richer recent-history and mission retrieval in chat
- structured rover intent parsing
- LangGraph mission planning and approval checkpoints
- AI-assisted command staging or execution

The AI Chat system prompt is intentionally read-only and must not publish rover control commands.

## Video Pipeline Model

The GCS uses separate ingest and delivery modes.

Current implemented mode:
- ingest: `mqtt_frames`
- delivery: `websocket_mjpeg`

Planned future modes:
- ingest: `rtp_udp`, `rtsp`, `whip`
- delivery: `webrtc_direct`, `webrtc_sfu`

## Current Priority

The current bootstrap path is functional:
- browser sends control to GCS
- GCS publishes MQTT control frames
- simulator publishes telemetry and JPEG camera frames
- GCS relays telemetry and frames to browsers

The next work is:
- actual `rover-sim-next` backend implementation
- spatial query service extraction and an agent-ready tool registry
- supervised rover intent parsing and mission draft planning
- RAG/web-grounded AI Chat source controls
- live map on the main dashboard
- simulator-side logging
- future synchronized recorded video support

## Repository Note

`gcs_server/` is tracked under the parent `remote-rover/` repository root.

That is the intended structure for ongoing development.
