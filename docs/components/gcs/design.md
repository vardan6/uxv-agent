# GCS — Design

Status date: 2026-06-01.

**How** the GCS is built — runtime model, browser workflow, MQTT integration, AI chat model, settings, file layout, and current limitations. Implementation-flexible companion to [requirements.md](./requirements.md). The requirements doc wins on product intent and operator-visible behavior; this doc wins on implementation specifics.

Status note: the GCS is the most complete component. The AI workspace (`/ai`) is fully implemented for Chat and read-only Agent modes, direct mission review/editing on `MapWidget`, and backend-owned mission revision execution with stale-state recovery. The Mission Planner Modernization work (ADRs [0021](../../cross-cutting/decisions/0021-mission-lifecycle.md)/[0022](../../cross-cutting/decisions/0022-gps-master-coordinate-frame.md)/[0023](../../cross-cutting/decisions/0023-behavior-tree-missions-relocatable-executor.md), Phases 1–6) has since landed on `feat/gps-master-coordinate-frame`: external controller link (pymavlink + MAVSDK adapters with health/read/write/clear), a relocatable behavior-tree executor that uploads nav segments to the FC, GPS-master WGS84 coordinate truth, the flat-Mission lifecycle UI, and a real 2D basemap render mode. Replay still uses its separate `static/replay.js` surface; video transport hardening remains a later slice. For live phase/slice status see `roadmap.md`.

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
| `ui/MissionListPanel.js` | Flat-Mission list (ADR 0021 §2: one row = one Mission) with Visible/Selected/Active state, per-row edit + legacy linear-plan upload (▶), and batch show/hide; row markup escapes AI-/operator-derived names |
| `layers/SceneObjectsLayer.js` | Renders the static 3d-env scene (roads, objects, spawn) from `/api/replay/scene-map`, matching replay |
| `ui/BasemapPanel.js` | Optional real 2D WGS84 basemap (OSM tiles, EPSG:3857) plotting the focused mission by lat/lon; default-off toggle (ADR 0022 Phase 4) |
| `ui/SelectionPanel.js` | Waypoint-level details and provenance display for selected waypoint |
| `ui/ContextMenu.js` | Right-click/long-press context menu (insert before/after, delete, set as home, detach) |
| `ui/HintToasts.js` | Gesture hint toasts |
| `ui/KeyboardHelpOverlay.js` | Keyboard shortcut reference overlay |
| `ui/ElevationProfilePanel.js` | Mission elevation profile panel for the selected overlay |
| `data/missionMutationApi.js` | Client-side mutation API calls with `client_version` CAS |
| `state/` | Frontend mission state management |

The widget's primary scene view uses `L.CRS.Simple` with local scene metres for overlay coordinates. Under ADR 0022 (GPS-master) WGS84 is the stored truth: overlay payloads now carry `lat/lon/alt` on every feature point plus the Mission `origin` datum, and the optional `BasemapPanel` plots the focused mission (and geofence) by lat/lon on a real EPSG:3857 basemap. The default `CRS.Simple` scene view still derives local metres from the WGS84 truth via the origin datum.

For the map widget design spec and phase 1A–1E delivery plan, see [design.md](./design.md).

For AI context, intent parsing, and planning-shell wiring, see [design.md](./design.md).

Current status of follow-on map work:

- the mission elevation profile panel is implemented on `/ai`
- the replay page still renders through `static/replay.js`, not through `MapWidget`
- geofence authoring + validation now have a real backend source: a mission's
  inclusion fence is stored on mission content (`geofence`), authored via the
  `set_mission_geofence` AI tool or the BasemapPanel `🛡 Fence` draw mode
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
- geofence is authored + enforced (ADR 0023 Phase 5) and a stored inclusion fence now renders on the basemap on load (overlay payload carries `geofence` + per-Mission `origin`; `BasemapPanel` draws the saved polygon/rally points distinct from the in-progress sketch)
- LLM provider checks are simple endpoint probes, not full chat completions
- bounded lazy data branches/source controls are implemented for replay, AI memory, settings, and sensor metadata; RAG/document retrieval and web research/search are still not implemented
- perception tool contract and video-frame understanding are not implemented yet
- command staging and execution approval require a separate future safety design
- AI chat is read-only and cannot publish rover control commands
- mission lifecycle now includes a durable backend execution transition **and** real external flight-controller handoff via the `ControllerMissionAdapter` (pymavlink/MAVSDK) driven by the behavior-tree executor (ADR 0023); the remaining gap is an exercised SITL/real-FC smoke loop (deferred under the no-tests rule until a target exists)

## Topic-Level Design Files

Detailed per-topic design content lives in sibling files under [`design/`](./design/). This is topic-level organization within the design tier (same stability rules as this file), not a separate tier. See ADR 0010 for history of the prior `internals/` split and its supersession.

- [`design/api-and-runtime.md`](./design/api-and-runtime.md) — Api And Runtime
- [`design/llm-capability-matrix.md`](./design/llm-capability-matrix.md) — Llm Capability Matrix
- [`design/map-widget.md`](./design/map-widget.md) — Map Widget
