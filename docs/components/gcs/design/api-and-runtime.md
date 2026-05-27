# GCS Technical Details

## Runtime Model

The GCS is a FastAPI application with a WebSocket-driven browser UI.

Its durable runtime concerns are:

- browser connection management
- in-memory current-state tracking
- MQTT runtime integration
- control publication
- AI session and context orchestration

## Control Ownership Model

Browser control is owned by one active dashboard client at a time.

Design rules:

- the latest focused and visible dashboard browser becomes the active
  controller
- other connected browsers may observe without becoming the publisher
- browser button states are collected by the GCS, not published directly by
  browsers to MQTT
- browser blur or hidden state clears inputs and deactivates browser control
- the GCS publishes MQTT control frames at `control_hz`

This keeps browser clients off the broker directly and preserves the GCS as the
control-plane authority.

Keyboard bindings come from shared config. UI defaults are fallback behavior,
not the source of truth.

## MQTT Runtime Behavior

The GCS subscribes to simulator state and camera topics and publishes:

- control frames
- presence frames keyed by `gcs_id`

### Presence Rule

Presence payloads include `gcs_id`, `active`, `timestamp`, browser-count
information, and the current active-controller identity.

Default `active` semantics:

- `active` is true when at least one browser WebSocket is connected, unless a
  forced value is used for shutdown or will-handling

## In-Memory State Boundary

The local state backend tracks:

- latest telemetry payload
- latest video-frame metadata
- broker connection status and freshness timestamps
- active controller and last-input timestamp
- video-mode settings

That model is sufficient for the current single-process deployment and is not a
multi-instance coordination design.

## Frontend Delivery Model

Current browser updates are delivered over WebSocket.

Telemetry, broker status, controller state, and video updates should continue
to be projected from backend-owned runtime state rather than letting browsers
infer those facts from independent broker reads.

## Settings Model

Settings remain config-backed rather than route-backed.

Durable rules:

- `llm_providers` stores provider configuration
- `model_routing` stores purpose-based model routing
- selected-section JSON import/export ignores missing sections rather than
  deleting newer settings
- raw API keys are never exported; provider settings use `secret_ref` names
- shared config also owns `key_bindings`, which are consumed consistently by
  both dashboard control UI and AI settings answers

Provider checks validate reachability and secret availability only. They do not
send prompts or publish rover control commands.

## AI Chat Boundary

The `/ai` surface is a provider-backed Chat/Agent workspace with supervised
non-executing side paths such as intent testing and the planning shell.

Durable rules:

- ordinary chat requests receive a compact read-only current-context block
- current context is assembled from runtime state, loaded settings, configured
  LLM provider metadata, scene-map data, replay summaries, and current mission
  state
- sensitive values stay redacted from AI context
- retry rebuilds context from the latest GCS state rather than replaying the
  old assistant context snapshot
- Agent mode uses tool surfaces for on-demand detail instead of preloading all
  large context into the prompt

Mission boundary:

- canonical mission state lives in the flat `MissionRepository`
- `mission_execution_service` is the controller handoff boundary only
- the `/ai` map widget consumes the flat Mission API directly
  (`/api/ai/missions[...]`); legacy revision/draft endpoints and the
  transitional `revision_id` overlay alias have been removed. The
  controller-state field is `active_mission_id`.
- mission-level `DELETE /api/ai/missions/{id}` is **soft** (sets
  `deleted_at`); it is rejected with HTTP 409 when the controller has the
  mission `executing` or `armed`. `POST /api/ai/missions/{id}/restore` flips
  the row back. `#index` is never reused (ADR 0021 § 2).

## Current Architecture Limits

Open architectural limits still include:

- no shared-state backend for coordinated multi-instance deployment
- presence semantics are still single-GCS oriented
- video transport remains a practical path, not a final production transport
