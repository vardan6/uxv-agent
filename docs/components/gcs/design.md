# GCS — Design

Status date: 2026-05-20.

**How** the GCS is built — runtime model, browser workflow, MQTT integration, AI chat model, settings, file layout, and current limitations. Implementation-flexible companion to [requirements.md](./requirements.md). The requirements doc wins on product intent and operator-visible behavior; this doc wins on implementation specifics.

Status note: the GCS is the most complete component. The AI workspace (`/ai`) is fully implemented for Chat and read-only Agent modes, direct mission review/editing on `MapWidget`, and backend-owned mission revision execution with stale-state recovery. Replay still uses its separate `static/replay.js` surface, and real external controller handoff plus video transport hardening remain the next slices.

## Table of Contents

- [Scope](#scope)
- [What Is Implemented](#what-is-implemented)
- [Runtime Model](#runtime-model)
- [Browser Workflow](#browser-workflow)
- [Presence And Telemetry Enablement](#presence-and-telemetry-enablement)
- [AI Chat And Agent Model](#ai-chat-and-agent-model)
- [Settings Model](#settings-model)
- [Main Files](#main-files)
- [Current Limitations](#current-limitations)

## Scope

`gcs_server/` is the browser-facing Ground Control Station for the Remote Rover project.

It is responsible for:

- serving the dashboard UI
- managing browser connections
- letting one focused dashboard browser control the rover at a time
- publishing MQTT control frames
- receiving telemetry and camera frames
- relaying telemetry and video to browsers
- publishing GCS presence so the simulator knows whether outbound data is currently needed

## What Is Implemented

- FastAPI backend
- browser dashboard
- WebSocket updates for telemetry, broker state, controller ownership, and video
- focus-driven single-controller activation
- config-backed keyboard controls and on-screen browser controls
- MQTT control publication
- MQTT telemetry subscription
- MQTT camera-frame subscription
- MQTT setup page with live reconfiguration
- periodic and event-driven GCS presence publication
- replay scene-map payload generated from the shared terrain scene manifest
- settings tabs for Connectivity, Video, Appearance, Add LLM Provider, and JSON
- LLM provider registration, editing, enable/disable state, provider checks, and model routing
- selected-section JSON settings export/load/save/apply (shipped: merged 2026-05-05)
- `/ai` provider-backed Chat and read-only Agent modes
- session-level source controls and bounded lazy retrieval surfaces for replay reports, AI chat history, safe settings/config, and sensor metadata
- `/ai` intent-test path for non-executing structured rover-task parsing
- `/ai` planning-shell path for non-executing mission-draft planning with approval gates (reached via `/plan <prompt>`)
- route-planning drafts and QGC `.plan` export for approved route-bearing drafts
- backend-owned mission revision storage, current mission-state APIs, overlay APIs, and controller mission-state APIs
- durable mission execution transition with controller-version checks and execution-attempt persistence
- stale execute recovery that refocuses the active revision and can auto-create a rebased revision on controller-version mismatch
- persistent AI sessions and messages
- streaming chat responses, retry, archive/restore, purge, session search, and per-session provider override
- compact live current-context injection for AI Chat
- structured rover/runtime/settings/LLM/map/replay context providers for AI Chat
- read-only agent tools for rover state, scene summary, object queries, mission state, and replay analytics
- structured rover intent parsing with optional deterministic target-resolution hints
- mission-draft storage and approval/reject flow with two-approval model
- planning shell reached through `/plan`: planner-loop planning core, durable checkpointer, interrupt-driven approval and clarification gates, streaming NDJSON events, approval and clarification cards in UI

Current execution-boundary status:

- the universal agent remains the product center
- mission drafts remain the planning artifact for now
- the backend mission execution boundary now exists and owns canonical mission revisions, overlays, controller snapshot state, and durable execution attempts
- the current adapter is still internal to the monolith; real external controller/MAVLink handoff remains the next implementation slice

## Runtime Model

The GCS is a FastAPI application with a WebSocket-driven browser UI.

The backend assembles four main runtime concerns:

- browser connection management
- in-memory state tracking
- MQTT runtime integration
- control publication loop

For the HTTP and WebSocket surface, see [design.md](./design.md).

## Browser Workflow

1. browser loads the dashboard
2. browser opens WebSocket to the GCS
3. browser receives the current runtime snapshot
4. the focused and visible dashboard browser becomes active
5. while focused and visible, browser sends held-button state changes
6. GCS publishes control frames to MQTT
7. telemetry and video received from MQTT are pushed back to all connected browsers

Keyboard bindings are read from shared config `key_bindings`. The default arrow-key and `W/A/S/D` mapping remains a fallback only. This keeps dashboard control answers in AI Chat aligned with the actual browser controls.

Control activation invariants (do not regress):

- Control must not auto-release on a timeout; only focus/visibility changes or a real disconnect may deactivate browser control.
- The focused and visible dashboard browser is the active controller inside `gcs_server`.
- Losing dashboard focus must publish neutral controls immediately so motion cannot stick.

## Presence And Telemetry Enablement

One important current responsibility of the GCS is presence signaling.

The GCS publishes a retained presence record on:

- `{topic_prefix}/{gcs_presence_topic}/{gcs_id}`

Current behavior:

- presence is refreshed periodically
- presence is published immediately on browser connect/disconnect and controller changes
- presence is marked inactive on shutdown or disconnect through the MQTT last-will path
- simulator auto-publishing depends on these presence messages

This makes the GCS part of the simulator bandwidth-control loop.

## AI Chat And Agent Model

Current AI Chat behavior:

- `/ai` is a provider-backed Chat/Agent workspace
- the live composer exposes Chat and Agent as the visible modes
- `/intent <prompt>` and the planning shell (via `/plan <prompt>`) remain available as supervised non-executing side paths
- `/plan` is the current explicit planning-shell entry point; there is no separate visible planning product mode
- LLM provider configuration comes from `llm_providers` and `model_routing`
- runtime chat calls go through the GCS LangChain provider registry
- Agent mode is wired through `ToolRegistry`; tools cover rover state, scene summary, object queries, mission state, and replay analytics

For the AI agent architecture and tool contract, see the [AI Agent component](../ai-agent/README.md).

## Map Widget

The `/ai` page hosts a `MapWidget` (`static/map/MapWidget.js`) below the chat panel. It is the primary mission authoring surface and the live vehicle view during mission execution.

Key frontend modules under `static/map/`:

| Module | Role |
|---|---|
| `MapWidget.js` | Root widget; Leaflet init, layer orchestration, keyboard shortcuts |
| `layers/LiveVehicleLayer.js` | Renders live vehicle position from `/ws` telemetry; polling fallback at 2 s |
| `layers/MissionOverlayLayer.js` | Renders mission route overlays with per-waypoint provenance styling |
| `ui/MissionListPanel.js` | Mission list grouped by operation; status badges; Approve draft / Execute mission buttons |
| `ui/SelectionPanel.js` | Waypoint-level details and provenance display for selected waypoint |
| `ui/ContextMenu.js` | Right-click/long-press context menu (insert before/after, delete, set as home, detach) |
| `ui/HintToasts.js` | Gesture hint toasts |
| `ui/KeyboardHelpOverlay.js` | Keyboard shortcut reference overlay |
| `ui/ElevationProfilePanel.js` | Mission elevation profile panel for the selected overlay |
| `data/missionMutationApi.js` | Client-side mutation API calls with `client_version` CAS |
| `state/` | Frontend mission state management |

The widget uses `L.CRS.Simple` with local scene metres for all overlay coordinates. Export-side projection (local → WGS84) is handled by `MissionExportService` on the backend. Lat/lon is never used inside the widget itself.

For the map widget design spec and phase 1A–1E delivery plan, see [design.md](./design.md).

For AI context, intent parsing, and planning-shell wiring, see [design.md](./design.md).

Current status of follow-on map work:

- the mission elevation profile panel is implemented on `/ai`
- the replay page still renders through `static/replay.js`, not through `MapWidget`
- geofence display and validation are still gated on a real backend source
- the main dashboard still does not have a dedicated live map panel

## Settings Model

JSON settings import/export (shipped 2026-05-05) supports selected sections:

- connectivity
- video
- appearance
- LLM providers
- model routing

Missing sections are ignored on apply so older JSON files do not erase newer settings. Raw API key values are not exported; provider settings use environment-variable `secret_ref` names. Import previews changes before applying.

Shared config also contains `key_bindings`, which the dashboard reads for browser keyboard control. These bindings are also included in the AI Chat settings context so questions about configured controls use the same source as the UI.

## Main Files

- `app.py`: FastAPI routes and WebSocket endpoint
- `scene_map.py`: replay scene-map payload from `config/terrain_scene.v1.json`
- `runtime.py`: service assembly and reconfiguration
- `mqtt_service.py`: MQTT connection, subscriptions, control publish, presence publish
- `control.py`: held-button control loop
- `state.py`: local runtime state and freshness tracking
- `ws.py`: WebSocket connection manager
- `ai/`: current-context service, provider registry, chat service, session storage, and secret storage
- `static/`: dashboard and setup frontend assets

## Current Limitations

- state is still in memory only
- no authentication or authorization
- current video delivery is still the bootstrap WebSocket path fed from MQTT frames
- multi-instance GCS behavior is not yet fully hardened
- replay map rendering still lives in `static/replay.js`; replay has not been migrated onto `MapWidget`
- geofence display and validation await a real backend source
- LLM provider checks are simple endpoint probes, not full chat completions
- bounded lazy data branches/source controls are implemented for replay, AI memory, settings, and sensor metadata; RAG/document retrieval and web research/search are still not implemented
- perception tool contract and video-frame understanding are not implemented yet
- command staging and execution approval require a separate future safety design
- AI chat is read-only and cannot publish rover control commands
- mission lifecycle now includes a durable backend execution transition, but it still stops before real external flight-controller/MAVLink handoff; that is the next implementation slice


---

# Merged from internals/ (2026-05-26)

The following sections were previously maintained as separate files under `docs/components/gcs/internals/`. Pass-1 + Pass-2 trim left them ≥80% design-shaped, so they have been folded into this design.md verbatim. ADR 0010 (which named the `internals/` tier) is superseded by this consolidation.


---

<!-- source: docs/components/gcs/design.md -->

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

Mission-execution boundary:

- canonical mission revision and controller-cutover state live behind the
  backend `mission_execution` boundary
- planning-shell compatibility flows may still sync into that boundary, but the
  GCS should treat `mission_execution` as the durable owner of mission state

## Current Architecture Limits

Open architectural limits still include:

- no shared-state backend for coordinated multi-instance deployment
- presence semantics are still single-GCS oriented
- video transport remains a practical path, not a final production transport


---

<!-- source: docs/components/gcs/design.md -->

# LLM Provider Agent Capability Rule

## How GCS currently decides “agent-capable”

In Agent mode, UI/runtime currently treats a provider as tool-capable when either:
- provider capabilities include `tool_calling` or `planner`, or
- provider type is not `ollama` (fallback heuristic in UI).

Reference: [static/ai.js](/mnt/c/Users/vardana/Documents/Proj/remote-rover/gcs_server/static/ai.js)

## Durable Rule

The durable product rule is:

- explicit capability metadata should be the primary signal
- `tool_calling` is sufficient for tool-using agent mode
- `planner` also qualifies a provider for agentic planning paths
- non-`ollama` fallback should be treated as a compatibility heuristic, not a long-term contract
- placeholder model IDs must be treated as unknown until replaced with concrete models and validated
- local models may need explicit conformance checks even when the serving stack advertises tool support

## Operational Guidance

- Prefer provider entries that declare `tool_calling` directly instead of relying on fallback inference.
- Keep `ollama` models behind tool-call conformance validation unless they have been verified in this environment.
- Do not rank placeholder or vendor-agnostic model IDs as agent-capable without concrete validation.
- Keep context-window comparisons out of durable design docs; they are dated operational snapshots.

The full provider-by-provider matrix is archival audit material rather than durable system design.


---

<!-- source: docs/components/gcs/design.md -->

# Map Widget

This document defines the durable design contract for the reusable mission map
widget used on `/ai` and later available to other GCS surfaces.

## Purpose

The widget gives operators spatial review of mission revisions and safe direct
manipulation of non-executing missions without collapsing approval and
execution into one action.

## Safety Invariants

These rules are non-negotiable:

1. approval is not execution
2. the client never mutates an executing mission
3. the client never silently overwrites authoritative mission state
4. the widget never invents backend contracts that do not exist

Implications:

- approval, rejection, and execution remain separate user actions
- all geometry mutation goes through backend round-trips
- missing backend features are hidden or disabled explicitly

## Backend Contracts

### Mission Overlay Payload

The widget consumes mission overlays from the backend mission-execution
surface.

The durable payload concepts are:

- `operation_id`
- `revision_id`
- `draft_id`
- `status`
- `goal`
- `waypoint_count`
- overlay `bounds`
- route-line and waypoint features

The backend overlay builder remains the source of truth for exact field shape.

### Coordinate System

Mission overlay points are local scene metres `{x, y, z}`, not WGS84
lat/lon.

Design rule:

- scene-mode rendering uses `L.CRS.Simple`
- WGS84 export remains a server-side concern
- any future WGS84 basemap mode must be a distinct widget mode with explicit
  CRS metadata

### Mission Revision List

Revision rows are grouped client-side by `operation_id`.

Design rules:

- one top-level row per operation
- default visible revision is the operation's active revision, falling back to
  the newest revision
- earlier revisions live under a collapsed earlier-revisions affordance
- executing revisions remain force-visible

### Approval, Rejection, And Execution

The widget uses existing backend transitions rather than inventing new ones.

Design rules:

- approval writes mission approval/export state but does not execute the rover
- execution is a separate explicit action with controller-version staleness
  checks
- rejection is a separate explicit action
- after any of these actions, the widget refreshes revision and overlay state

### Telemetry Source

The live vehicle layer uses existing GCS telemetry projection.

Design rule:

- the widget does not open an unrelated parallel telemetry model when `/ws`
  already provides the needed state

### Deferred Sources

These remain gated on real backend sources:

- mission revision push events
- geofence display and validation
- standalone export affordances
- home-point editing

## Frontend Module Boundary

The widget remains a small ES-module surface without a framework or build step.

Durable separation:

- one orchestrator widget
- layer modules for overlays and live vehicle state
- UI modules for mission list, selection, context actions, and help
- data modules for backend wrappers
- pure state/logic modules for edit state, mission grouping, and profile logic

Pure logic modules should remain DOM- and Leaflet-free so they stay easy to
test later.

## AI Chat Integration

The map is a secondary surface on `/ai`, below the main chat area.

Design rules:

- chat remains the primary interaction surface
- the widget supports container re-parenting and resize invalidation
- map state is driven by the active AI session

## Mission List Rules

Each operation row carries:

- visibility control
- status indication
- vehicle/profile identity
- mission name or equivalent label
- provenance/origin indicator
- action affordances appropriate to the revision state

Behavior rules:

- visible overlays are capped softly to avoid clutter
- focus applies fit-to-bounds and dims non-focused visible missions
- numbered waypoint badges remain visible because color alone is insufficient

## Map Rendering Rules

- proposed revisions render dashed and visually weaker
- approved revisions render solid and fully emphasized
- executing revisions render as locked
- superseded or completed revisions render dimmed
- fit-to-bounds uses the focused mission when one exists, else the visible-set
  union

## Accessibility And Keyboard Ownership

The widget shares a page with a keyboard-heavy chat composer.

Design rules:

- icon-only controls still require explicit accessible labels
- color never carries meaning by itself
- map keyboard shortcuts only fire when focus is inside the widget and not in a
  free-text input
- `Esc` closes menus/modals before clearing selection and exiting edit mode
- touch/mobile may degrade to read-only editing behavior, but the surface must
  remain usable

## Empty, Error, And Offline States

- when no mission overlay exists, the widget shows a no-mission state rather
  than a broken map
- overlay API failures surface as non-blocking retryable errors
- missing vehicle telemetry hides the live vehicle marker without blocking
  mission rendering
- missing vehicle-profile data falls back safely rather than blocking the UI

## Editing Model

### Core Rules

- editing is available only for non-executing revisions
- gesture handlers short-circuit on locked revisions
- client edits operate against backend-backed revision state with optimistic
  concurrency checks
- starting edits on a locked but non-executing revision may fork a new
  client-authored revision

### Gestures And Keyboard

The widget supports:

- waypoint selection and multi-selection
- waypoint dragging
- insert-before / insert-after behavior
- add-waypoint mode
- delete and focus shortcuts
- explicit help and context actions

The exact input affordances may evolve, but they must continue to respect the
locking and concurrency rules above.

### Provenance State Machine

Per-waypoint provenance stays explicit:

- `ai`
- `user`
- `ai+edited`

Design rule:

- once a waypoint is `ai+edited`, later AI regeneration must treat it as
  operator-modified and require explicit confirmation before replacement

### Hard Lock During Execution

While a revision is executing:

- edit, reject, and approve affordances are disabled
- drag/insert/delete gestures are blocked before state changes
- the revision remains visibly locked in both the list and map rendering

## Vehicle Profile Boundary

Vehicle profiles represent mission capability context, not per-waypoint editing
schema by themselves.

The widget may render profile identity and use it to drive map hints, but
vehicle capability fields and per-waypoint property editing remain separate
concerns.

## Deferred Beyond The Current Widget Contract

These stay outside the core widget contract until real backend/platform support
exists:

- replay-page migration details
- geofence display and validation
- WGS84 basemap mode
- edit-during-execution
- richer per-waypoint property schema editing
- floating/second-monitor window behavior beyond re-parenting support

