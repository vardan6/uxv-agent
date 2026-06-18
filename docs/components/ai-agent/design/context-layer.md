# AI Current Context Layer

## Purpose

The AI Current Context Layer gives `/ai` live, exact facts before any RAG system is added.

This layer exists because some facts are already known by the GCS and should not be recovered through vector search:
- latest rover telemetry
- telemetry and camera freshness
- broker/runtime state
- active controller state
- saved GCS/settings values such as MQTT topics, key bindings, video mode, and simulation identity
- configured LLM providers and model routing
- simulator backend identity
- current replay session summary
- structured terrain bounds, roads, and object geometry
- current mission state once mission storage exists

RAG is still planned, but it should be used for documents, reports, object definitions, mission memory, operator notes, and other knowledge sources where semantic retrieval is useful. It should not be the first source for exact live state or map geometry.

The current-context layer should remain compact. Larger terrain/object/replay/perception details are obtained on demand through deterministic tools served by `SpatialQueryService` and `ToolRegistry`. Bounded lazy retrieval/source controls cover replay, AI memory, settings, and sensor metadata; RAG source controls and web-grounded retrieval are out of scope here.

Retry intentionally rebuilds context from the latest rover/runtime/settings/map state instead of reusing the original assistant response context. This makes retry behave as "answer the latest user message again with current GCS facts." The original assistant message's stored `context_snapshot` remains available in message metadata for audit/debugging until that assistant message is deleted by retry.

## Current Context Sources

### Runtime And State Store Meaning

The current context layer does not create a second runtime or a second state database.

`AppRuntime` is the assembled live GCS process object. It holds:
- loaded `AppConfig`
- `LocalStateBackend`
- MQTT runtime
- control service
- replay store
- AI session store
- LLM secret store
- WebSocket manager

`LocalStateBackend` is the in-memory current-state store for the running GCS process. It holds facts that change while the GCS is running:
- latest telemetry snapshot
- broker connection state and freshness timestamps
- active browser controller and last input timestamp
- video mode state and latest video-frame metadata

The AI current context reads from these existing objects. It does not create a new control path and does not publish commands.

### Rover Current State

Source:
- latest telemetry received by the GCS from MQTT

Store:
- `LocalStateBackend`

Included facts:
- telemetry freshness
- last telemetry timestamp and age
- backend identity
- local position
- GPS position
- heading
- speed
- battery/power data
- camera mode
- camera freshness

### Runtime Current State

Source:
- GCS runtime state and loaded configuration

Store:
- `LocalStateBackend`
- loaded `AppConfig`
- active `ReplayStore`

Included facts:
- MQTT broker state
- active controller summary
- video modes
- simulation backend identity
- configured map/site data
- current replay session ID

### Settings Current Context

Source:
- loaded `AppConfig`
- `config/common.local.json` when present
- `config/common.example.json` fallback values

Included facts:
- settings file path
- MQTT broker host and port
- MQTT topic prefix
- MQTT control, telemetry, camera, and GCS presence topics
- MQTT control rate and telemetry policy values
- configured key bindings for control actions
- configured video ingest/delivery modes
- GCS host/port and freshness settings
- simulator backend identity and available backend names
- map/site defaults
- AI text-to-speech settings

This source is intended for exact settings questions such as:
- broker host or port
- configured MQTT topics
- key used for a control action
- video ingest/delivery mode
- simulator backend
- AI voice/TTS settings

These are examples, not a fixed whitelist. Any setting included in the context can be answered using the same mechanism.

### LLM Current Context

Source:
- `llm_providers` in the loaded GCS config
- `model_routing` in the loaded GCS config
- stored-secret availability from the GCS LLM secret store

Included facts:
- active AI session ID and provider override state
- purpose-based model routing
- General Chat routing rule
- active chat provider resolved for the current request
- active chat provider source: session override, General Chat route, first enabled provider, or none
- provider IDs and display names
- provider type
- model ID
- base URL
- enabled/disabled state
- capabilities
- authentication mode summary
- whether a secret reference is configured
- whether a stored secret exists for stored-secret providers
- latest provider check status fields

Secret handling:
- raw API keys are not included
- stored secret values are not included
- environment variable values are not included
- the context may include safe booleans such as `uses_secret`, `secret_ref_configured`, and `has_stored_secret`

This is what "redacted settings" means in this project: sensitive values are withheld, not merely shortened.

Session-specific behavior:
- AI send and retry endpoints pass the active `session_id` into `AIContextService`
- if the session has a provider override, that provider is reported as the active chat provider
- otherwise the active provider is resolved from General Chat routing, then the first enabled provider fallback
- assistant message metadata still stores the provider/model actually used for each response

### Scene Map And Object Facts

Source:
- `config/terrain_scene.v1.json`

Included facts:
- backend
- terrain bounds
- terrain size
- source path
- road count
- object count
- object kinds
- spawn point
- site name

Deterministic object queries:
- objects in front of the rover within a max distance and field of view
- objects near the rover within a radius
- objects by kind

Scene payload grid size:
- AI context currently loads the scene map with `grid_size=32`.
- `grid_size` controls the sampled heightmap resolution included in the scene payload. It does not change object centers, object sizes, terrain bounds, roads, or spawn coordinates, which come from the source scene manifest.
- The low grid size is intentional for compact context and tool payloads. If future spatial queries use terrain height/collision detail rather than object centers and 2D distances, those queries should request a higher or native-resolution terrain representation explicitly.

### Mission Current State

Planned facts:
- active mission ID
- goal
- status
- plan summary
- approval state
- execution state
- monitoring notes

### Recent History

Source:
- replay SQLite database

Current surfaces:
- active replay session summary
- recent telemetry samples

Future additions:
- recent controls
- recent runtime events
- compact active replay narrative
- later RAG-backed document/project knowledge and optional web-grounded retrieval

## Chat-Time Flow

Current flow:

```text
user message
  -> FastAPI AI endpoint
  -> AIContextService.build_compact_context()
  -> selected detail providers based on the question
  -> AIChatService
  -> LangChain message list
  -> SystemMessage(read-only behavior)
  -> SystemMessage(live GCS current context)
  -> conversation messages
  -> configured chat model
  -> assistant response
  -> ai_messages.meta_json stores context snapshot/provider names
```

The context block is intentionally compact. It is meant to keep high-signal live facts in the model input without turning every prompt into a full telemetry dump.

## Query Behavior

The current context has two kinds of data.

Always included:
- compact rover state
- compact runtime state
- compact settings context
- compact LLM/provider context
- compact mission state
- compact scene-map summary

Query-triggered details:
- larger or more specific data added only when the user asks for it
- examples include objects in front of the rover, objects near the rover, objects by kind, current replay summary, and recent telemetry samples
- future examples include objects to the left/right, objects inside a sector, route-intersecting objects, dynamic detected objects, and mission validation details
- in agent mode, spatial query-triggered details are not preloaded into the prompt; the read-only agent tools fetch them on demand
- the always-on set is scoped by need-frequency (ADR 0029): rover, mission, and scene summaries stay always-on because most operator turns depend on them; `runtime`/broker/sim/map config is tool-loaded (`get_runtime_context`) because it is rarely the answer. Lazy loading is applied only where data is usually *not* needed — lazy-loading a usually-needed surface would add a round-trip to most turns
- rover and scene are injected once (the compact block), not duplicated as synthetic turn-0 tool calls (ADR 0029 removes that duplicate)

This keeps normal questions small while still allowing richer answers for spatial and recent-history questions.

Examples:

```text
What is the rover state?
```

Uses (compact always-on summaries):
- current rover state
- mission summary
- scene summary

Runtime/broker config is no longer in the always-on set (ADR 0029); the agent
calls `get_runtime_context` if a question actually needs it.

```text
What objects are in front of the rover within 100 meters and 20 degrees?
```

Uses:
- current rover pose
- structured scene-map objects
- deterministic distance and bearing calculation

Does not use:
- vector RAG
- MQTT control

```text
What is the current mission?
```

Uses:
- mission current-state provider

Current answer should indicate:
- no active mission storage/workflow exists yet

```text
What is the broker port?
```

Uses:
- settings current context
- `settings.mqtt.broker_port`

```text
What model is configured for General Chat?
```

Uses:
- LLM current context
- `llm.general_chat_route`
- matching provider entry in `llm.providers`

```text
What happened recently?
```

Uses:
- active replay session summary
- recent telemetry samples

## Important Architecture Decision

The project will not add a retained MQTT current-state topic for now.

Current decision:
- MQTT remains the telemetry/control transport
- GCS owns the first current-state layer because it already receives telemetry and owns browser/runtime state
- AI Chat uses structured current-state providers before RAG
- RAG comes later for docs, reports, object definitions, mission history, and source-linked knowledge
- Redis or another shared state service is deferred until multiple processes or multiple GCS backends need shared low-latency state

## Boundaries

The current context layer is read-only.

It must not:
- publish MQTT control commands
- stage rover commands
- start missions
- bypass the existing controller lock
- claim that AI Chat can operate the rover

It may:
- summarize current rover/runtime/map state
- answer object-position questions from structured scene geometry
- report stale telemetry or missing camera data
- say that no active mission state exists
- provide context for future read-only tools and mission drafting

## Forward-Looking Plan

RAG integration plan:
- keep exact live state in this context layer
- add RAG collections for project docs, rover docs, operator notes, reports, mission memory, and semantic object definitions
- merge current-context metadata and RAG citation metadata on assistant messages
- extend the existing `/ai` source controls to future RAG/web-grounded surfaces only after those providers exist

Mission workflow plan:
- use current context for initial mission drafting
- store mission drafts and approval state separately from chat text
- keep execution behind explicit operator approval and controller/safety checks

Related: [Spatial Tools](./spatial-tools.md) · [Graph Spec](./graph-spec.md) · [Replay Access](./replay-access.md) · [Requirements](../requirements.md).
