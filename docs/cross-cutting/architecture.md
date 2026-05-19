# Architecture

## System Overview

The current system is organized as two applications plus a shared runtime configuration layer.
The next AI architecture step adds one important internal subsystem inside
the GCS: backend-owned mission execution.

```text
Browser Operator
  -> HTTP / WebSocket
GCS Server
  -> MQTT Broker
3D Simulator
```

The current simulator rover is the prototype target, but the intended architecture is broader: a remote robot operations stack where the GCS can later supervise real rovers and other robot backends. AI agents are expected to sit above the GCS/control boundary, generate missions from text or voice prompts, use map and sensor context, monitor execution, and escalate to a human when policy or unexpected conditions require it.

Repository structure:

```text
remote-rover/
  3d-env/
  gcs_server/
  config/
  tools/
  docs/
```

## Application Responsibilities

### 1. 3D Simulator

Location:
- `3d-env/`

Primary responsibilities:
- simulate rover motion and environment
- accept local keyboard input
- accept remote control from MQTT
- generate telemetry payloads
- capture simulated camera frames
- publish telemetry and camera frames when allowed by the telemetry policy
- expose operator settings for MQTT and simulator runtime behavior

### 2. GCS Server

Location:
- `gcs_server/`

Primary responsibilities:
- serve the browser UI
- manage browser WebSocket connections
- enforce single-controller ownership
- publish MQTT control frames
- subscribe to telemetry and camera topics
- relay telemetry and video to browser clients
- publish GCS presence information so the simulator can decide whether outbound publishing is needed
- expose browser-based MQTT setup and runtime reconfiguration
- expose LLM provider, model-routing, video, appearance, and selected-section JSON settings
- provide read-only provider-backed AI Chat with persistent sessions
- provide structured current rover/runtime/settings/LLM/map/replay context to AI Chat before RAG
- provide a first read-only Agent mode with tools for rover state, scene summary, object queries, mission state, and replay analytics
- provide mission proposal, mission revision, and future controller handoff orchestration through a backend mission execution boundary

### 3. Shared Config

Location:
- `config/`

Primary responsibilities:
- keep simulator and GCS aligned on runtime contract values
- store shared MQTT topic names and rates
- store GCS host/port defaults
- store video mode defaults
- store browser keyboard control bindings
- store the telemetry publishing policy and GCS presence topic settings
- store GCS-side LLM provider definitions and purpose-based model routing

### 4. Terrain Scene Manifest

Location:
- `config/terrain_scene.v1.json`

Primary responsibilities:
- define the current terrain heightfield
- define roads, spawn points, and static world objects
- provide the shared map/scene source for both the simulator and GCS
- avoid hard-coded terrain object names, counts, coordinates, and dimensions in runtime scripts

## Data Flows

### Browser Control Flow

```text
Browser
  -> WebSocket control messages
GCS
  -> MQTT control/manual
Simulator
```

Current behavior:
- browsers never publish directly to MQTT
- the GCS owns control publication
- one browser holds the control lock at a time
- the GCS publishes control frames at `mqtt.control_hz`

### Telemetry Flow

```text
Simulator
  -> MQTT telemetry/state
GCS
  -> WebSocket telemetry
Browser
```

Current behavior:
- the simulator emits rover state payloads on the configured telemetry topic
- the GCS subscribes and tracks freshness
- browsers receive telemetry snapshots through the GCS

### Camera Flow

```text
Simulator POV buffer
  -> MQTT camera-feed
GCS
  -> WebSocket video_frame
Browser
```

Current behavior:
- the simulator captures JPEG frames from the POV camera
- the GCS decodes and relays frames to browsers
- this path is currently the implemented bootstrap solution

### GCS Presence Flow

```text
GCS
  -> MQTT gcs/presence/<gcs_id> (retained + periodic)
Simulator
```

Current behavior:
- the GCS publishes a retained presence record per GCS instance
- the simulator subscribes to the presence wildcard topic
- in `auto` mode, the simulator only publishes outbound data if at least one GCS presence record is active and fresh

## MQTT Contract Summary

Current shared topic model:
- `{topic_prefix}/{control_topic}`
- `{topic_prefix}/{state_topic}`
- `{topic_prefix}/{camera_topic}`
- `{topic_prefix}/{gcs_presence_topic}/{gcs_id}`

Default values from shared config:
- `topic_prefix`: `/projects/remote-rover`
- `control_topic`: `control/manual`
- `state_topic`: `telemetry/state`
- `camera_topic`: `camera-feed`
- `gcs_presence_topic`: `gcs/presence`

## Telemetry Publishing Policy

Current simulator policy values:
- `auto`
- `force_on`
- `force_off`

Policy evaluation:
- `force_on`: always publish outbound simulator telemetry and camera frames
- `force_off`: never publish outbound simulator telemetry and camera frames
- `auto`: publish only while at least one active GCS presence entry is fresh

Freshness source:
- the GCS publishes presence with a timestamp
- the simulator checks the timestamp age against `mqtt.gcs_presence_timeout_ms`

This design is more reliable than checking whether telemetry values changed, because a stationary rover can still have an active operator session.

### GCS Settings Flow

```text
Browser Settings UI
  -> FastAPI settings endpoints
GCS runtime config
  -> config/common.local.json
```

Current behavior:
- MQTT connectivity changes are persisted and trigger a live GCS MQTT reconnect
- video mode changes are persisted and broadcast to browser clients
- simulation backend identity changes are persisted and roll over the replay session
- LLM provider and model-routing changes are persisted for AI Chat and future rover-agent workflows
- keyboard control bindings are read from shared config by the dashboard and exposed to AI Chat as settings context
- JSON settings import/export can operate on selected sections without clearing missing sections from older files

LLM provider records use `secret_ref` environment-variable names. Raw API key values are not exported through the JSON settings path.
Raw API key values and stored secret values are also not injected into AI Chat context.

### AI Chat Flow

```text
Browser AI Chat
  -> FastAPI AI session/message endpoints
GCS current-context providers
  -> compact live context block
GCS AI service
  -> LangChain provider adapter
Configured LLM provider
```

Current behavior:
- `/ai` is a read-only Chat/Agent workspace
- chat sessions and messages persist in SQLite
- the selected model comes from General Chat routing or a per-session provider override
- OpenAI-compatible providers and Ollama are supported by the current runtime adapter
- chat responses can stream to the browser
- each send/retry call receives a compact current-context block after the read-only system prompt
- assistant messages store current-context snapshots and provider names in `ai_messages.meta_json`
- Agent mode has synchronous read-only tools for current rover state, scene summary, front/near/by-kind object queries, current mission state, and replay analytics
- Agent tools use the request's prebuilt context snapshot for async runtime facts and do not publish commands or mutate state
- the AI Chat system prompt does not allow direct rover control, mission execution, or MQTT command publication

### Mission Proposal And Execution Flow

Target near-term flow:

```text
Operator / universal agent request
  -> Agent runtime + planning shell
  -> semantic mission proposal package
Mission execution subsystem
  -> canonical mission revision store + policy + operation lifecycle
  -> immediate overlay event for UI
  -> approval / cutover decision
  -> controller adapter
  -> verification / rollback / rebasing
```

Key boundary:
- the agent proposes
- mission execution owns authoritative mission lifecycle and controller-facing behavior

### AI Current Context Flow

```text
LocalStateBackend
  -> rover telemetry, broker freshness, controller, video modes
AppConfig
  -> MQTT settings, key bindings, video/GCS/simulation/map/AI settings
LLM provider config
  -> provider/model/routing summaries with secrets redacted
ReplayStore
  -> active replay summary, recent telemetry
scene_map.py
  -> terrain bounds, roads, object geometry
Mission execution providers
  -> current mission revision state, overlays, controller mission snapshot state
AIContextService
  -> compact prompt context + metadata
AIChatService
  -> LangChain messages + assistant metadata
```

Current behavior:
- live rover and runtime facts are structured data, not RAG documents
- saved settings and LLM routing/provider summaries are structured data, not RAG documents
- terrain/object facts come from the explicit scene manifest
- object-in-front and object-near-rover queries are computed deterministically from rover pose and object geometry
- the default AI context should remain compact; larger terrain/object/replay/perception details should be retrieved on demand through tools
- in Agent mode, duplicate keyword-triggered spatial prompt details are skipped and the model is expected to call read-only tools
- mission current state now comes from backend mission revision storage and durable controller mission state
- there is no retained MQTT current-state topic

Design reason:
- MQTT remains the telemetry/control transport
- the single-process GCS is the first current-state owner because it already receives telemetry and owns browser/runtime state
- RAG is reserved for project docs, reports, semantic object definitions, mission history, operator notes, and other source-linked knowledge
- a shared state backend such as Redis can be added later when multiple processes or multiple GCS instances need shared low-latency state

Implemented (Phase 3 and earlier):
- `SpatialQueryService` — deterministic geometry service with 9 methods; used by agent tools and intent parsing
- `ToolRegistry` — permissioned per-request tool registry; Agent mode rewired through it; `ReadOnlyAgentToolset` removed; current tool declarations include `tier`, `required_scopes`, and `side_effects`
- `PolicyEngine` seam — thin tool-call policy evaluation before execution; current enforcement preserves read-only / non-executing behavior
- shared compact data-access manifest used by Agent chat context and planning-shell graph state
- structured rover intent parsing (`IntentService`) and mission-draft workflow (`MissionDraftService`)
- LangGraph planning shell (Phases 1–3): deterministic draft flow, durable checkpointer, interrupt-driven approval and clarification gates

Implemented after Phase 4:
- `classify_request_scope`, lazy data branches (replay, AI memory, settings, sensor), and bounded source controls
- assistant/planning-shell metadata now records `retrieved_sources`, `loaded_data_refs`, and `retrieval_citations`

Planned next behavior (Phase 5+):
- RAG/source toggles, document upload, and citations
- web research/search as a grounded chat source
- command staging and execution approval (separate safety design required)

### Future AI Mission Flow

```text
User text/voice prompt
  -> outside AI agents
  -> mission draft
  -> human approval / policy validation
  -> autopilot or controlled GCS execution
  -> robot backend
```

Parallel monitoring path:

```text
Telemetry + map + video + future sensors
  -> AI monitoring agents
  -> continue / replan / escalate / stop decision
  -> operator report when human judgment is required
```

Future sensor context may include camera image processing, lidar, infrared, ultrasonic, and other robot-specific observations.
Some later agents may run onboard the robot for perception or local safety; the next planned implementation focus is outside agents in the GCS/backend.

## Runtime Boundaries

### In The Simulator

Current important modules:
- `simulator/main.py`: runtime loop, publish gating, control merge, status bar updates
- `simulator/mqtt_bridge.py`: MQTT client, topic subscription, presence tracking, publish helpers
- `simulator/gui.py`: top menu and status bar, including telemetry policy menu
- `simulator/settings_gui.py`: settings dialogs and MQTT config fields
- `simulator/terrain.py`: manifest-backed terrain heightfield, visual mesh, road coloring, and Bullet collision mesh
- `simulator/rover.py`: rover physics and motion

### In The GCS

Current important modules:
- `gcs_server/app.py`: FastAPI routes, WebSocket endpoint, runtime wiring
- `gcs_server/mqtt_service.py`: broker connection, subscriptions, control publish, presence publish
- `gcs_server/control.py`: control loop and held-button publishing
- `gcs_server/state.py`: in-memory runtime state and freshness tracking
- `gcs_server/ws.py`: browser connection manager
- `gcs_server/runtime.py`: service assembly and reconfiguration
- `gcs_server/scene_map.py`: scene-map payload from `config/terrain_scene.v1.json`
- `gcs_server/ai/context_service.py`: live current-context providers for AI Chat
- `gcs_server/ai/spatial_query_service.py`: deterministic spatial/geometry query service
- `gcs_server/ai/tool_registry.py`: permissioned per-request tool registry for Agent and planning-shell flows
- `gcs_server/ai/intent_service.py`: structured rover intent parsing with repair
- `gcs_server/ai/mission_draft_service.py`: mission-draft CRUD, validate, approve/reject
- `gcs_server/ai/workbench_graph.py`: LangGraph planning graph (Phases 1–3)
- `gcs_server/ai/graph_state.py`: `WorkbenchGraphState` TypedDict
- `gcs_server/ai/graph_runtime.py`: `WorkbenchGraphRuntime` service container
- `gcs_server/ai/provider_registry.py`: configured provider to LangChain model adapter
- `gcs_server/ai/chat_service.py`: read-only Chat/Agent orchestration
- `gcs_server/ai/session_store.py`: SQLite AI session/message storage
- `gcs_server/ai/migrations.py`: AI store schema migrations

## Current Architectural Strengths

- applications are cleanly separated
- shared runtime contract is centralized
- browser clients are isolated from direct MQTT publication
- presence-based publish gating reduces unnecessary simulator bandwidth
- exact current rover/map/runtime facts are available to AI Chat without vector RAG
- first on-demand read-only spatial/state/replay tools are available to Agent mode
- the system already demonstrates an end-to-end operator workflow

## Current Architectural Gaps

- no distributed state backend yet
- no auth boundary yet
- no production media transport yet
- no finalized multi-GCS operational model yet
- runtime config is still local-file based
- RAG/document retrieval and durable LangGraph mission workflows are not implemented yet
- current command-staging and execution workflows are not implemented yet
- current mission state is still a placeholder, not a persisted mission model
