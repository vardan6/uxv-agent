# GCS Technical Details

## Runtime Model

The GCS is a FastAPI application with a WebSocket-driven browser UI.

The backend assembles four main runtime concerns:
- browser connection management
- in-memory state tracking
- MQTT runtime integration
- control publication loop

## HTTP And WebSocket Surface

Current important routes:
- `/`: dashboard page
- `/setup/mqtt`: MQTT setup page
- `/api/health`: health summary
- `/api/snapshot`: current runtime snapshot
- `/api/config`: raw loaded config
- `/api/mqtt-config`: get and update MQTT settings
- `/api/simulation-config`: get and update current simulator backend identity
- `/api/video-mode`: update video mode flags
- `/api/llm-settings`: get or replace LLM provider and routing settings
- `/api/llm-providers`: list and create LLM provider records
- `/api/llm-providers/{provider_id}`: update an LLM provider record
- `/api/llm-providers/{provider_id}` with `DELETE`: delete an LLM provider record
- `/api/llm-providers/{provider_id}/check`: probe a saved provider
- `/api/llm-providers/check-draft`: probe an unsaved provider draft
- `/api/model-routing`: get or update purpose-based model routing
- `/api/ai/sessions`: list or create AI chat sessions
- `/api/ai/sessions/{session_id}`: get, update, or archive an AI chat session
- `/api/ai/sessions/{session_id}/restore`: restore an archived AI chat session
- `/api/ai/sessions/{session_id}/purge`: permanently delete an AI chat session
- `/api/ai/sessions/{session_id}/messages`: send a non-streaming AI chat message
- `/api/ai/sessions/{session_id}/messages/stream`: send a streaming AI chat message
- `/api/ai/sessions/{session_id}/retry`: retry the last assistant response
- `/api/ai/sessions/{session_id}/retry/stream`: retry the last assistant response with streaming
- `/api/ai/sessions/{session_id}/intent-test`: parse a rover task into structured intent without executing anything
- `/api/ai/sessions/{session_id}/workbench/stream`: stream the planning shell (`workbench_*` is the historical code namespace)
- `/api/ai/sessions/{session_id}/workbench/thread/{thread_id}/resume`: resume approval/clarification interrupts for the planning shell
- `/api/ai/mission-revisions`: list mission revisions
- `/api/ai/mission-revisions/current`: fetch current mission state, active revision, and overlay
- `/api/ai/mission-revisions/{revision_id}`: fetch one mission revision
- `/api/ai/mission-revisions/{revision_id}/overlay`: fetch one revision's overlay payload
- `/api/ai/mission-revisions/{revision_id}/execute`: trigger mission execution cutover for a stored revision
- `/api/ai/mission-overlays/current`: fetch the current mission overlay by session
- `/api/ai/controller-mission`: fetch durable controller mission state
- `/api/settings/export`: export selected settings sections
- `/api/settings/load-from-path`: load and preview selected settings sections from a config file
- `/api/settings/save-to-path`: save selected settings sections to a config file
- `/api/settings/apply`: apply selected settings sections to active runtime config
- `/api/replay/sessions`: list replay sessions
- `/api/replay/sessions/rollover`: manually roll over the active replay session
- `/api/replay/sessions/{session_id}`: get or delete replay session details
- `/api/replay/scene-map`: return replay map payload from the terrain scene manifest
- `/api/controller/take`: claim control
- `/api/controller/release`: release control
- `/ws`: browser WebSocket endpoint

## Control Model

Current control ownership model:
- one active browser client at a time
- the latest focused and visible dashboard browser becomes active
- other connected browsers may observe
- browser button states are collected by the GCS
- browser blur or hidden state clears inputs and deactivates browser control
- the GCS publishes MQTT control frames at `control_hz`

This keeps browser clients off the broker directly and gives the GCS a clean control-plane role.

Keyboard control bindings are loaded from shared config `key_bindings`.
The dashboard keeps default `W/A/S/D` and arrow-key bindings only as a fallback if config loading fails.

Current key-binding config shape:

```json
{
  "key_bindings": {
    "forward": ["arrow_up", "w"],
    "backward": ["arrow_down", "s"],
    "left": ["arrow_left", "a"],
    "right": ["arrow_right", "d"],
    "camera_toggle": ["v"]
  }
}
```

This keeps keyboard controls configurable and makes config the source of truth for both the dashboard and AI Chat answers. Future input devices such as USB joysticks should follow the same pattern: add a config-backed device/action mapping instead of hard-coding device controls in UI or runtime code.

## MQTT Runtime Behavior

### Subscriptions

The GCS subscribes to:
- `{topic_prefix}/{state_topic}`
- `{topic_prefix}/{camera_topic}`

### Publications

The GCS publishes:
- control frames to `{topic_prefix}/{control_topic}`
- presence frames to `{topic_prefix}/{gcs_presence_topic}/{gcs_id}`

### Presence Payload

Current presence payload includes:
- `gcs_id`
- `active`
- `timestamp`
- `browser_count`
- `active_controller_id`

Current `active` rule:
- active is true when at least one browser WebSocket is connected, unless a forced value is used during shutdown or will handling

## In-Memory State Model

The current local state backend tracks:
- latest telemetry payload
- latest video frame metadata
- broker connection status and freshness timestamps
- active controller and last input timestamp
- video mode settings

This is enough for the current single-process deployment model, but not enough for coordinated multi-instance operation.

## Frontend Delivery Model

Current frontend update channels:
- telemetry over WebSocket JSON
- broker status over WebSocket JSON
- controller state over WebSocket JSON
- video frames over WebSocket JSON carrying decoded MQTT-frame data

Current implemented video mode:
- ingest: `mqtt_frames`
- delivery: `websocket_mjpeg`

## Settings Model

Current settings pages:
- Connectivity
- Video
- Appearance
- Add LLM Provider
- JSON

LLM provider settings are stored in `llm_providers`.
Model routing settings are stored in `model_routing`.

Provider checks currently probe provider metadata endpoints:
- Ollama: `/api/tags`
- other configured providers: `/models`

These checks validate reachability and secret availability only.
They do not send prompts, create chat sessions, or publish rover control commands.

JSON settings import/export supports selected sections:
- connectivity
- video
- appearance
- LLM providers
- model routing

Missing sections are ignored on apply so older JSON files do not erase newer settings.
Raw API key values are not exported; provider settings use environment-variable `secret_ref` names.

Shared config also contains `key_bindings`, which the dashboard reads for browser keyboard control. These bindings are also included in the AI Chat settings context so questions about configured controls use the same source as the UI.

## AI Chat Model

Current AI Chat behavior:
- `/ai` is a provider-backed Chat/Agent workspace
- the live composer exposes Chat and Agent as the visible modes
- `/intent <prompt>` and the planning shell (via `/plan <prompt>`) remain available as supervised non-executing side paths
- LLM provider configuration still comes from `llm_providers` and `model_routing`
- runtime chat calls go through the GCS LangChain provider registry
- OpenAI-compatible providers and Ollama are supported by the current adapter layer
- sessions and messages are stored in SQLite at the configured `ai_sessions_db_path`
- Agent loop traces are written as JSONL under the configured `agent_trace_dir`
- read-only trace inspection endpoints expose recent trace summaries and full stored events: `GET /api/ai/traces`, `GET /api/ai/traces/{trace_id}`
- the chat page supports Chat and Agent run modes, streaming responses, retry, archive/restore, purge, session search, and provider override
- `Intent Test` behavior is reached through a separate endpoint and slash-command surface rather than a persistent top-level composer mode
- each chat request receives a compact live current-context block after the read-only system prompt
- the context block includes saved settings context and configured LLM/provider context
- the current AI Chat system prompt is read-only and explicitly says not to control the rover, publish commands, or start missions
- retry intentionally rebuilds context from the latest GCS state instead of replaying the original assistant response context

Current mission-execution boundary:

- `mission_execution` now exists as a distinct backend boundary owning
  canonical mission revision state, mission overlays, controller mission
  versioning, execution attempts, verification state, and rollback-ready
  snapshots
- install/read-back now goes through an injected controller adapter seam,
  while SQLite remains the backend audit/projection store for mission
  execution state
- compatibility paths still exist where the planning shell and
  `MissionDraftService` participate in approval/export flow before syncing
  into `mission_execution`
- the next architectural step is replacing the default local file-backed
  adapter with a real external controller transport and moving more of the
  approval/cutover semantics fully behind `mission_execution`

Important status clarification:

- the shared universal-agent design is the target direction
- the current default runtime is still transitional
- ordinary Agent turns and the planning shell are not yet fully unified

Current-context provider architecture:
- `ai/context_service.py` owns read-only context construction for AI Chat
- `LocalStateBackend` remains the first store for latest telemetry, broker freshness, controller state, and video mode state
- loaded `AppConfig` provides exact settings facts such as MQTT broker, topics, control rate, key bindings, video mode, simulator identity, map defaults, and AI TTS settings
- `llm_providers` and `model_routing` provide provider/model/routing facts for chat questions about configured LLMs
- the AI session ID is passed into context construction so per-session provider overrides can be reflected in the active chat provider summary
- `scene_map.py` remains the structured source for terrain bounds, roads, and object IDs/kinds/labels/positions/sizes
- `ReplayStore` provides current replay session summaries and recent telemetry samples
- `get_current_mission_state()` now reads from backend-owned mission revisions and includes controller mission state when available
- object queries such as objects in front of the rover are computed from current rover pose and structured scene-map geometry, not vector RAG
- Agent mode is wired through `ToolRegistry`; `ToolRegistry.build_langchain_tools(runtime, context_snapshot, timezone_name, permissions)` provides synchronous LangChain tools for rover state, scene summary, front/near/by-kind object queries, mission state, and replay analytics (`ReadOnlyAgentToolset` removed)
- agent tools close over the request's prebuilt context snapshot for async runtime facts; they do not await inside LangChain's synchronous tool loop
- agent mode skips duplicate keyword-triggered spatial context enrichment and uses tools for those details
- assistant message metadata stores the context snapshot and provider names in `ai_messages.meta_json`

Intent parsing behavior:
- `ai/intent_service.py` parses an operator prompt into a validated structured JSON object
- provider routing for parsing resolves in this order: `command_parser`, then `planner`, then `general_chat`
- the parser prompt requires JSON-only output, constrained intent types, explicit motion classification, and missing-information reporting
- one repair pass is attempted if the first model response is invalid JSON or fails schema validation
- when parsed intent implies rover motion and includes a target, the backend may run deterministic spatial target resolution to show candidate scene objects
- `Intent Test` remains non-executing even when it performs target resolution

Sensitive LLM values are redacted from AI context. The model can see safe auth summaries such as whether a provider uses a secret and whether a stored secret exists, but it does not receive raw API keys, stored secret values, or environment-variable values.

AI context uses two inclusion levels:
- compact settings/runtime/provider facts are included on every send and retry
- larger detail providers are added only when the user asks for them, such as recent telemetry or objects in front of the rover
- in agent mode, spatial detail providers are primarily on-demand tools rather than preloaded prompt sections

Agent-mode limitation:
- streaming transport is newline-delimited JSON (`application/x-ndjson`)
- normal chat streams assistant deltas
- streaming Agent mode emits per-tool progress events: `agent_tool_start` and `agent_tool_result`

The current design intentionally does not publish a retained MQTT current-state topic. MQTT remains the telemetry/control transport, while GCS-owned current-state providers serve exact live facts to AI Chat. A shared state service such as Redis can be added later if multiple processes need the same low-latency state.

Detailed reference:
- [AI Context Layer](../../ai-agent/internals/context-layer.md)
- [Rover Intents And Intent Test](../../ai-agent/internals/intent-parsing.md)

Current AI Chat storage:
- `ai_sessions`: session title, mode, provider override, timestamps, archive state
- `ai_messages`: role, content, provider/model metadata, latency, and JSON metadata

The AI session database is separate from replay storage. LLM provider records remain in the GCS settings JSON rather than being duplicated into the AI session database.

## Technical Gaps Still Open

- move runtime state to Redis or equivalent shared backend
- define multi-GCS presence semantics more explicitly
- secure configuration and control endpoints
- introduce a production-grade video transport path
- add RAG source controls, document upload, retrieval metadata, and citations
- add web research/search integration
- expand rover-state, replay-log, mission, and terrain/object context providers in AI Chat
- add explicit UI policy controls and live projection of controller mission state into the `/ai` workflow
- replace the local durable mission-execution adapter with a real controller upload/read-back adapter
- add automatic stale-version rebase flow on top of the current compare-and-swap rejection
