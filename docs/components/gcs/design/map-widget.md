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
- per-Mission `origin` datum and an optional stored `geofence` (WGS84) for basemap display

The backend overlay builder remains the source of truth for exact field shape.

### Coordinate System

Mission overlay points now carry both local scene metres `{x, y, z}` and WGS84
`{lat, lon, alt}` truth (ADR 0022). The server derives whichever side is missing
from the per-Mission `origin` datum, so a frame can't drift.

Design rule:

- scene-mode rendering uses `L.CRS.Simple` and consumes `{x, y, z}`
- the WGS84 basemap mode is a distinct widget mode (`BasemapPanel`, own
  `L.map` on EPSG:3857) that plots `{lat, lon}` directly — no client-side
  re-projection
- WGS84 remains the server-side stored truth

### Flat Mission List

One row per flat Mission (ADR 0021 §2 — one row = one Mission). Focus and
visibility are keyed on the Mission id; the revision/operation history is
internal detail behind an optional per-row expander, not the row itself.

Design rules:

- one top-level row per Mission, identified by its stable `#index`
- row edit/execute resolve to the Mission's **active revision** and are gated by
  its status: `executing` → locked (🔒, no edit/execute); `approved` /
  `exported` / `cutover_pending` → executable; the broader editable set also
  includes `proposed` / `awaiting_approval` / `planning`. `approve`/`reject`
  stay off the flat row (draft plumbing is internal)
- three-state selection model (ADR 0021 §4): **Visible** (overlay shown),
  **Active** (focused; click promotes a Mission to Active+Visible), and
  **Selected** (checkbox / shift-click range → batch Show/Hide/Clear). The
  invariant "Active must be Visible" is enforced; a new Mission auto-promotes to
  Active+Visible (not Selected)
- earlier revisions of a Mission live under a collapsed expander affordance
- an executing Mission remains force-visible

### Approval, Rejection, And Execution

The widget uses existing backend transitions rather than inventing new ones.

Design rules:

- approval writes mission approval/export state but does not execute the rover
- the sidebar ▶ button is a **legacy linear-plan upload** (ADR 0023): it pushes
  the active revision's waypoints to the controller as a `.plan` and starts them
  via `execute_revision` (`POST /api/ai/mission-revisions/{id}/execute`). It is
  **not** the behavior-tree session executor — lifecycle BT runs are
  AI-tool/banner driven (`arm_execution`/`execute_mission` + `/api/ai/execution/*`)
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

Known gap (Phase 6 top priority, 2026-06-01): the scene-mode render is **not yet at
parity with the replay page**. The widget draws the terrain heightmap
(`TerrainCanvasLayer`) plus mission/vehicle layers, but has **no scene-objects layer**
— the replay page renders 3d-env objects from the `/api/replay/scene-map` `objects`
payload (`scene_map.py`), the widget does not. It also only fits-to-bounds off mission
overlays, so with **no mission focused** the view stays at `setView([0,0],1)` and shows
nothing. Required fix: add a scene-objects layer (port replay's object render) and
fit/center to scene bounds on load so the 3d-env map renders standalone. This is the
real blocker to manual-authoring and AI-overlay testing; see `roadmap.md` Phase 6.

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
- edit-during-execution
- richer per-waypoint property schema editing
- floating/second-monitor window behavior beyond re-parenting support
