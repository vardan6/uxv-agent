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

The current context layer does not create a second runtime or state database.
It reads from the assembled `AppRuntime`, `LocalStateBackend`, and a small set
of existing read-only stores already owned by the GCS.

Durable source groups:

- **Rover/runtime state** from MQTT-fed telemetry and local runtime state:
  freshness, pose, heading, speed, battery/power, camera freshness, broker
  state, active controller summary, video mode, simulator backend identity,
  and current replay session.
- **Settings** from loaded config: broker host/port, topic names, control-rate
  policy, key bindings, video ingest/delivery mode, host/port, map/site
  defaults, backend identity, and related exact-value settings questions.
- **LLM/provider state** from `llm_providers`, `model_routing`, and secret-store
  availability: routing rules, resolved active provider, provider metadata,
  safe secret-presence booleans, and latest provider-check summaries.
- **Scene facts** from `config/terrain_scene.v1.json`: terrain bounds, terrain
  size, road/object counts, object kinds, spawn point, and deterministic object
  queries such as "in front of rover", "near rover", and "by kind".
- **Mission state** from the backend mission surface: current mission rows,
  overlay-backed summaries, and execution-relevant mission status when present.
- **Recent history** from replay storage: active replay-session summary and
  bounded recent telemetry samples.

Secret handling is strict: raw API keys, stored-secret values, and environment
variable contents never enter context; only safe booleans such as
`secret_ref_configured` or `has_stored_secret` may appear.

For scene payload size, the default `grid_size=32` remains intentional: object
positions, bounds, roads, and spawn coordinates come from the source manifest,
while higher-resolution terrain sampling should be requested explicitly by tools
that need it.

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

The context has two classes of data:

- **Always included**: compact rover, runtime, settings, provider, mission,
  and scene summaries.
- **Query-triggered**: larger deterministic details such as object-near-rover
  queries, replay-session summaries, recent telemetry samples, or other
  bounded expansions the user explicitly asks for.

In agent mode, these larger spatial/history details are fetched on demand
through tools rather than preloaded into every prompt. This keeps routine
questions small without losing exactness.

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

Related: [Spatial Tools](./spatial-tools.md) · [Graph Spec](./graph-spec.md) · [Replay Access](./replay-access.md) · [Requirements](../requirements.md).
