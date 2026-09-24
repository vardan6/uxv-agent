# GCS — Design

**How** the GCS is built — runtime model, browser workflow, MQTT integration, AI chat model, settings, file layout, and current limitations. Implementation-flexible companion to [requirements.md](./requirements.md). The requirements doc wins on product intent and operator-visible behavior; this doc wins on implementation specifics.

The mission architecture is governed by ADRs
[0021](../../cross-cutting/decisions/0021-mission-lifecycle.md),
[0022](../../cross-cutting/decisions/0022-gps-master-coordinate-frame.md), and
[0023](../../cross-cutting/decisions/0023-behavior-tree-missions-relocatable-executor.md).

Mission Console is now the main browser entry point. `/` redirects to
`/mission-console`; the previous manual-control dashboard remains available at
`/dashboard`. The console is a composition layer over existing surfaces, not a
second implementation of replay, Missions, or AI Session behavior.

> **Terminology — "dashboard" vs "Drive Console".** Uses of "dashboard" in this
> document describe the **current `/dashboard` implementation** (page id, file
> names, focus-driven controller code). The product term for that teleoperation
> surface is now **Drive Console** (see [requirements.md](./requirements.md)
> §Drive Console). They refer to the same surface; the rename is product-facing
> and does not change the implementation names below. The greenfield Operator
> Console ([ADR 0030](../../cross-cutting/decisions/0030-greenfield-operator-console-frontend.md))
> replaces this surface with widgets; this doc remains current-implementation truth
> until that migration lands.

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

`backend/` is the browser-facing Ground Control Station for the Remote Rover project.

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
- `/ai` Chat and Agent paths, including direct Agent mission-authoring through shared planning tools
- route-planning drafts and QGC `.plan` export for approved route-bearing drafts
- backend-owned mission revision storage, current mission-state APIs, overlay APIs, and controller mission-state APIs
- durable mission execution transition with controller-version checks and execution-attempt persistence
- stale execute recovery that refocuses the active revision and can auto-create a rebased revision on controller-version mismatch
- persistent AI sessions and messages
- streaming chat responses, retry, archive/restore, purge, session search, and per-session provider override
- compact live current-context injection for AI Chat
- structured rover/runtime/settings/LLM/map/replay context providers for AI Chat
- read-only agent tools for rover state, scene summary, object queries, mission state, and replay analytics
- structured rover intent parsing as a shared internal capability with optional deterministic target-resolution hints
- mission-draft storage and approval/reject flow with two-approval model
- Agent mission-authoring through shared planning tools: planner loop inside the normal Agent runtime, deterministic mission validation/storage, and normal chat responses instead of planner-only interrupt cards

Execution-boundary design:

- the universal agent remains the product center
- mission drafts remain the planning artifact for now
- the backend mission execution boundary now exists and owns canonical mission revisions, overlays, controller snapshot state, and durable execution attempts
- external controller handoff has since landed (ADR 0023 Phases 1–3): a `ControllerMissionAdapter` interface with pymavlink and MAVSDK implementations (health probe, read/write/clear, version CAS), and a relocatable behavior-tree executor that flattens nav segments to `.plan` and installs them through the adapter, gated by the ADR 0021 Strict/Confirm/Autonomous modes

## Runtime Model

The GCS is a FastAPI application with a WebSocket-driven browser UI.

The backend assembles four main runtime concerns:

- browser connection management
- in-memory state tracking
- MQTT runtime integration
- control publication loop

For the HTTP and WebSocket surface, see [design.md](./design.md).

## Browser Workflow

Mission-focused workflow starts in Mission Console:

1. browser loads `/mission-console`
2. replay sessions are listed from the existing replay API
3. `MapWidget` renders the mission map and Missions surface
4. AI Session chat reuses the existing `/ai` frontend/runtime behavior

Manual driving still uses the dashboard:

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
- The focused and visible dashboard browser is the active controller inside `backend`.
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
- there is no separate visible planning product mode; mission-authoring now
  happens through the primary Agent experience
- LLM provider configuration comes from `llm_providers` and `model_routing`
- runtime chat calls go through the GCS LangChain provider registry
- Agent mode is wired through `ToolRegistry`; tools cover rover state, scene summary, object queries, mission state, and replay analytics
- terminal clients use the same `/api/ai/...` backend surface; the original CLI
  delivery plan is retained only as
  [historical context](../../archive/gcs/2026-06-16-ai-cli-plan.md)
- the removal history for legacy `/intent` and `/plan` entry points is retained
  in the [archive](../../archive/gcs/2026-06-17-intent-plan-cleanup.md)

For the AI agent architecture and tool contract, see the [AI Agent component](../ai-agent/README.md).

### AI chat frontend layout

The `/ai` chat layout is owned by `frontend-vanilla/ai.html`, `frontend-vanilla/ai.js`, and
`frontend-vanilla/style.css`. Its sessions/sidebar resizer should follow the lighter
`MapWidget` list-resizer pattern: keep the usable hit target, make the visible
divider narrow and low contrast, and let the adjacent panel own any subtle
border. Do not fork resize semantics away from the current AI chat behavior:
saved sidebar width, pointer capture, ARIA separator values, keyboard arrow
resizing, and the mobile rule that hides the divider must keep working.

Visual cleanup of the chat workspace should be CSS-first unless a behavior bug
requires JavaScript. It must not touch AI session/message storage, provider
routing, streaming/retry/stop behavior, source controls, or `MapWidget`
mission/map behavior.

## Map Widget

The `/ai` page hosts a `MapWidget` (`map/MapWidget.js`) below the chat panel. It is the primary mission authoring surface and the live vehicle view during mission execution.

Key frontend modules under `map/`:

| Module | Role |
|---|---|
| `MapWidget.js` | Root widget; Leaflet init, layer orchestration, keyboard shortcuts |
| `sources/authored/LiveVehicleLayer.js` | Renders live vehicle position from `/ws` telemetry; polling fallback at 2 s |
| `sources/authored/MissionOverlayLayer.js` | Renders mission route overlays with per-waypoint provenance styling |
| `ui/MissionListPanel.js` | Flat-Mission list (ADR 0021 §2: one row = one Mission) with Visible/Selected/Active state, five fixed per-row action slots (play/pause, stop, edit, delete, visibility), batch show/hide. Row markup escapes AI-/operator-derived names. See [requirements.md §Mission Row Button Layout](../gcs/requirements.md#mission-row-button-layout) for slot spec. |
| `sources/world/SceneObjectsLayer.js` | Renders the static 3d-env scene (roads, objects, spawn) from `/api/replay/scene-map`, matching replay |
| `ui/BasemapPanel.js` | Real 2D WGS84 basemap view (OSM tiles, EPSG:3857) plotting the focused mission by lat/lon; owns only basemap rendering plus WGS84 sketch capture for the shared toolbar |
| `ui/MapAuthoringToolbar.js` | Shared bottom authoring toolbar owned by `MapWidget`; routes add-waypoint, corridor/survey generation, geofence save/clear, and sketch state/status through existing mission handlers |
| `ui/SelectionPanel.js` | Waypoint-level details and provenance display for selected waypoint |
| `ui/ContextMenu.js` | Right-click/long-press context menu (insert before/after, delete, set as home, detach) |
| `ui/HintToasts.js` | Gesture hint toasts |
| `ui/KeyboardHelpOverlay.js` | Keyboard shortcut reference overlay |
| `ui/ElevationProfilePanel.js` | Mission elevation profile panel for the selected overlay |
| `sources/authored/missionMutationApi.js` | Client-side mutation API calls with `client_version` CAS |
| `state/` | Frontend mission state management |

The widget's primary scene view uses `L.CRS.Simple` with local scene metres for overlay coordinates. Under ADR 0022 (GPS-master) WGS84 is the stored truth: overlay payloads now carry `lat/lon/alt` on every feature point plus the Mission `origin` datum, and `BasemapPanel` plots the focused mission (and geofence) by lat/lon on a real EPSG:3857 basemap. The default `CRS.Simple` scene view still derives local metres from the WGS84 truth via the origin datum. Basemap is a map VIEW, not a separate authoring mode; mission authoring controls belong to the shared bottom authoring toolbar.

The bottom map info bar shows live cursor `x/y` in local scene metres, sampled terrain ground `z` at the cursor, WGS84 when a Mission origin exists, and single-waypoint selection detail. Ground `z` is sampled from the same scene heightmap used by the terrain render so the operator can author or inspect routes against the current terrain surface without switching views.

For the map widget design spec and phase 1A–1E delivery plan, see [design.md](./design.md).

For AI context and intent parsing, see [design.md](./design.md).

Map integration boundaries:

- the mission elevation profile panel is implemented on `/ai`
- the replay page still renders through `frontend-vanilla/replay.js`, not through `MapWidget`
- geofence authoring + validation now have a real backend source: a mission's
  inclusion fence is stored on mission content (`geofence`), authored via the
  `set_mission_geofence` AI tool or the map authoring toolbar's fence mode
  (`POST /api/ai/missions/{id}/geofence`), enforced early by the executor and
  uploaded to the FC (ADR 0023 Phase 5)
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

### Mission Lifecycle Tab

See [requirements.md §Mission Lifecycle Tab](../gcs/requirements.md#mission-lifecycle-tab) for the full field spec. For FC adapter protocol details and `mav-sim` integration see [`docs/mav-sim/design.md`](../../mav-sim/design.md).

## Main Files

- `app.py`: FastAPI routes and WebSocket endpoint
- `scene/scene_map.py`: replay scene-map payload from `scene/scenes/terrain_scene.v1.json`
- `runtime.py`: service assembly and reconfiguration
- `mqtt_service.py`: MQTT connection, subscriptions, control publish, presence publish
- `control.py`: held-button control loop
- `state.py`: local runtime state and freshness tracking
- `ws.py`: WebSocket connection manager
- `ai/`: current-context service, provider registry, chat service, session storage, and secret storage
- `frontend-vanilla/`: dashboard and setup frontend assets
- `map/`: the shared map widget (both frontends), split into
  `sources/world/` and `sources/authored/` per ADR 0037. The split is an
  isolation rule, not a filing convention: `sources/world/` must never import
  from `sources/authored/`, because world content is generated and read-only
  while authored content is operator-created and mutable. Neither direction
  imports the other today; only `MapWidget.js` composes both.
- `tools/` / `bin/` (planned): terminal AI CLI thin client over `/api/ai/...`

## Current Limitations

- state is still in memory only
- no authentication or authorization
- current video delivery is still the bootstrap WebSocket path fed from MQTT frames
- multi-instance GCS behavior is not yet fully hardened
- replay map rendering still lives in `frontend-vanilla/replay.js`; replay has not been migrated onto `MapWidget`
- geofence is authored + enforced (ADR 0023 Phase 5) and a stored inclusion fence now renders on the basemap on load (overlay payload carries `geofence` + per-Mission `origin`; `BasemapPanel` draws the saved polygon/rally points distinct from the in-progress sketch)
- LLM provider checks are simple endpoint probes, not full chat completions
- bounded lazy data branches/source controls are implemented for replay, AI memory, settings, and sensor metadata; RAG/document retrieval and web research/search are still not implemented
- perception tool contract and video-frame understanding are not implemented yet
- command staging and execution approval require a separate future safety design
- AI chat is read-only and cannot publish rover control commands
- mission lifecycle now includes a durable backend execution transition **and** real external flight-controller handoff via the `ControllerMissionAdapter` (pymavlink/MAVSDK) driven by the behavior-tree executor (ADR 0023); the remaining gap is an exercised SITL/real-FC smoke loop (deferred under the no-tests rule until a target exists)

## Topic-Level Design Files

Detailed per-topic design content lives in sibling files under [`design/`](./design/). This is topic-level organization within the design tier (same stability rules as this file), not a separate tier.

- [`design/api-and-runtime.md`](./design/api-and-runtime.md) — Api And Runtime
- [`design/llm-capability-matrix.md`](./design/llm-capability-matrix.md) — Llm Capability Matrix
- [`design/map-widget.md`](./design/map-widget.md) — Map Widget
- [`design/mission-sidebar-toolbar.md`](./design/mission-sidebar-toolbar.md) — Mission Sidebar Toolbar
