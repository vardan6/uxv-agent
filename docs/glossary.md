# Glossary

Shared vocabulary used across Remote Rover docs and code. When the same
term appears in multiple docs, this is the canonical definition.

## Active GCS Presence

A retained MQTT presence record published by a GCS instance with a recent
timestamp. The simulator uses these records to decide whether to publish
telemetry in `auto` mode. See
[Architecture](./cross-cutting/architecture.md#telemetry-publishing-policy).

## Agent Mode

The primary `/ai` operator mode. The model can use bounded tools, compact
live context, and approval/clarification surfaces when needed. Over time
this is intended to absorb most separate AI interactions that used to be
framed as distinct modes.

## ADR (Architectural Decision Record)

A short document recording a significant architectural choice, the
alternatives considered, and the consequences. Stored in
[decisions/](./cross-cutting/decisions/).

## AI Session

A persistent conversation with a configured LLM provider, identified by
`session_id`. Stores messages, current-context snapshots, provider
metadata, and source-control state. User-facing modes are Chat and Agent.

## Approval Card

The amber UI element shown when the planning shell has paused at a draft
approval step. Contains the proposed draft and Approve / Reject buttons.

## Approval Gate

A durable human-in-the-loop pause where the system waits for explicit
operator approve / reject input before continuing a planning flow.

## Backend Identity

A configuration value identifying which simulator backend (`3d-env` or
`rover-sim-next`) is currently active. Persisted in shared config and
reflected in telemetry.

## Bootstrap Video Path

The current MQTT-frame to WebSocket-MJPEG video delivery path. Functional
for development and demos, but not the intended long-term media transport.

## Chat Mode

A simpler `/ai` mode for plain conversation. No tools, no approval gates.
Useful today for provider testing and lightweight fallback behavior. Long
term it may remain as a narrow testing path while Agent becomes the main
operator-facing mode.

## Checkpointer

The LangGraph mechanism for persisting graph state at super-step
boundaries. Required for durable human-in-the-loop resume. Currently
`MemorySaver` (in-process). See
[decisions/0004-langgraph-checkpointer-choice.md](./cross-cutting/decisions/0004-langgraph-checkpointer-choice.md).

## Clarification Card

The amber UI element shown when the planning shell has paused to ask for
missing information. Lists missing-information items with Continue / Cancel
controls.

## Clarification Gate

A durable human-in-the-loop pause used when the agent needs more operator
input before it can continue safely or produce a valid draft.

## Command Staging

A planned but not implemented step that would queue an approved mission's
individual commands for explicit operator review before publication.
Distinct from draft approval. Requires a separate safety design.

## Compact Context

The small always-on live context block injected at the start of a run
before larger retrieval surfaces are used.

## Controller Lock

The single-controller ownership boundary. Only the focused, visible
dashboard browser holds the lock and may publish control frames. Releasing
focus releases the lock.

## Current Context Layer

The compact set of live structured facts (rover state, runtime, settings,
scene summary, replay summary) injected into AI prompts before larger
retrieval is used. See
[components/ai-agent/design.md](./components/ai-agent/design.md).

## Draft Approval

Operator approval of a non-executing planning artifact. Distinct from any
future execution approval.

## Execution Allowed

A boolean field on mission drafts, forced to `false` by the service layer.
No code path currently flips this to `true`. Distinct from
`requires_operator_approval`.

## Execution Approval

A separate future approval step that would authorize staged execution.
Currently not implemented.

## GCS

Ground Control Station — the FastAPI + browser application in
`gcs_server/` that operators use to monitor and control the rover.

## Intent

A structured interpretation of a natural-language operator request, with
fields like `intent_type`, `target`, `area`, `requires_rover_motion`,
`missing_information`. Produced by `IntentService` from the operator's
prompt.

## Lazy Retrieval

On-demand loading of larger *stored* information (replay reports, AI
memory, settings, sensor metadata) only when needed for the current run,
instead of front-loading it into every prompt. A subset of [On-Demand
Tools](#on-demand-tools), which also includes pure-computation tools that
do not load stored data.

## Mission Draft

A structured non-executing plan produced by the planning capability of the
agent. Always created with `execution_allowed: false`. Has an approval
status such as pending, approved, rejected, or superseded.

## Mission Lifecycle Mode

The configurable policy governing how a mission moves from creation to
execution. One of **Strict** (AI may only propose; operator clicks play),
**Confirm** (AI arms execution; operator confirms via banner within a
timeout), or **Autonomous** (AI may execute directly). Build-time defaults:
sim build → Autonomous, real-rover build → Strict. Runtime configurable via
`Settings → Mission Lifecycle`. Defined in
[decisions/0021-mission-lifecycle.md](./cross-cutting/decisions/0021-mission-lifecycle.md),
which supersedes the historical two-approval model.

## Mission Console

The primary GCS operator workspace for mission-focused work. It brings replay
session context, the mission map, Mission management, and AI Session chat into a
single page while preserving each surface's existing behavior and ownership.

## Model Routing

The mapping from AI purpose (General Chat, Mission Planner, Rover Intent
Parser, Reporter, Embeddings, Vision) to a primary and fallback LLM
provider. Persisted in shared GCS config.

## NDJSON Stream

The streaming response format for AI endpoints. Each line is a JSON object
describing one event such as a token delta, tool call, interrupt, or final
message.

## On-Demand Tools

Tools the AI can call to retrieve larger or computed data not kept in the
always-on context. Registered through `ToolRegistry`.

## Permission Class

A label on a registered tool indicating what category of action it
represents: `read_only`, `analysis`, `planning`. The classes
`command_staging` and `execution` are explicitly rejected by the registry.

## Presence Topic

The MQTT topic where GCS instances publish retained presence records.
Default: `{topic_prefix}/gcs/presence/{gcs_id}`.

## Provider

A configured LLM endpoint (OpenAI, OpenAI-compatible, Ollama, Anthropic,
Gemini, Mistral, NVIDIA NIM, OpenRouter, LM Studio, Custom HTTP). Each
provider has a display name, base URL, model ID, secret reference,
capabilities, and enabled state.

## Provider Override

A per-session AI setting that pins the session to a specific provider,
ignoring normal routing for that session.

## Purpose

A semantic role assigned to an LLM provider via model routing. Current
purposes: General Chat, Rover Intent Parser, Mission Planner, Reporter,
Embeddings, Vision / Object Description.

## RAG

Retrieval-Augmented Generation. The chat-grounding mechanism for project
docs, mission history, semantic object definitions, reports, and operator
notes. Reserved for semantic knowledge, not exact live state or geometry
(scope: [decisions/0003-rag-scope-vs-live-context.md](./cross-cutting/decisions/0003-rag-scope-vs-live-context.md)).
First consumer is `project_docs`, built on a Qdrant sidecar with the
ingestion pipeline in `rag_service/` and the query path in
`gcs_server/ai/retrieval.py`; see
[decisions/0028-rag-project-docs-first-consumer-qdrant.md](./cross-cutting/decisions/0028-rag-project-docs-first-consumer-qdrant.md).

## Read-Only Agent

Agent behavior operating with only `read_only` and `analysis` permission
tools — no planning, no command staging, no execution.

## Replay Session

A recorded period of GCS runtime persisted in SQLite. Contains telemetry,
control frames, runtime events, and camera timing metadata. Inspectable
via the `/replay` page.

## Rover Intent Parser

The LLM purpose / service responsible for converting a natural-language
operator prompt into a structured intent. Implemented as `IntentService`
with structured-output parsing and a single repair attempt.

## Scene Map / Terrain Scene Manifest

The single source of truth for static world geometry: terrain
heightfield, roads, spawn points, pads, solar panels, building parts,
trees, rocks. Stored at `config/terrain_scene.v1.json`. Consumed by both
simulator and GCS.

## SpatialQueryService

The deterministic geometry service that answers questions like "objects in
front of the rover," "objects within radius," and "nearest object by
kind." Backed by the scene manifest and rover pose.

## Telemetry Policy

The simulator's outbound publishing rule. Values: `auto` (publish only
when an active GCS is fresh), `force_on`, `force_off`.

## Tool Registry

The permissioned per-request registry that exposes tools to the AI
runtime. Rejects `command_staging` and `execution` permission classes at
registration time.

## Two-Approval Model

Historical term. Originally the boundary that separated draft approval
("this planning artifact is acceptable") from execution approval
("publish these commands to the rover"). Superseded by the
configurable **Mission Lifecycle Modes** (Strict / Confirm / Autonomous);
see [decisions/0021-mission-lifecycle.md](./cross-cutting/decisions/0021-mission-lifecycle.md).
Strict mode preserves separate operator authorization for execution and is the
shipped default for real-rover builds. See
[ADR 0021](./cross-cutting/decisions/0021-mission-lifecycle.md).

The three canonical operator verbs are:
- **Approve draft** — locks the revision; does not execute.
- **Execute mission** — the second, explicit gate that hands the approved revision to the flight controller.
- **Export plan** — exports an approved revision as a `.plan` file without executing.

The word "Accept" is not used in UI copy or documentation.

## MapWidget

The reusable Leaflet-based map component (`static/map/MapWidget.js`) used
on the `/ai` page and the Approval Card. Uses `L.CRS.Simple` with local
scene metres for all overlay coordinates — not lat/lon. Vehicle-aware: reads
the active `VehicleProfile` to drive property panels and dispatch validation.
See [design.md](./components/gcs/design.md).

## Mission Revision

A versioned snapshot of a mission's waypoint list and metadata, stored in
`mission_revisions`. Revisions are append-only and lineage-aware. Every
revision carries a `client_version` for optimistic concurrency and a
`vehicle_profile_id` binding. Provenance at the waypoint level is one of
`ai`, `user`, or `ai+edited`. See also **Waypoint Provenance**.

## `client_version` (Optimistic Concurrency)

An integer version counter on mission revisions used for optimistic CAS.
Every mutation request carries `expected_version`; the backend rejects stale
writes with `409 Conflict`. Editing a locked revision (`approved`,
`executing`, `completed`) forks a new client-authored revision rather than
mutating in place. There is no last-write-wins fallback.

## Waypoint Provenance

A per-waypoint field tracking the origin of each waypoint in a mission
revision. Values:
- `ai` — waypoint was emitted by the agent and has not been edited by the operator.
- `user` — waypoint was created by the operator from scratch.
- `ai+edited` — waypoint was originally AI-proposed and has since been edited by the operator.

The agent must diff and ask before overwriting `ai+edited` waypoints during
regeneration; this is enforced server-side. See
[design.md](./components/ai-agent/design.md).

## Universal Agent Runtime

The shared bounded reasoning loop that should power chat, grounded
investigation, planning, and future specialist behaviors. Project-specific
capabilities are added through tools, policy, memory, and workflow shells
around this core.
