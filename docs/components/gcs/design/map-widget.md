# Map Widget

This document defines the durable design contract for the reusable mission map
widget used on `/ai` and later available to other GCS surfaces. ADR 0021 makes
the flat Mission row the durable operator-facing object; any revision/draft API
shape described below is compatibility-only unless stated otherwise.

## Purpose

The widget gives operators spatial review of Missions and safe direct
manipulation of non-executing missions.

## Safety Invariants

These rules are non-negotiable (originally [ADR 0012](../../../cross-cutting/decisions/0012-map-widget-safety-invariants.md);
invariant 1 retired by [ADR 0022](../../../cross-cutting/decisions/0022-drop-operator-approval-gate.md)):

1. the client never mutates an executing mission
2. the client never silently overwrites authoritative mission state
3. the widget never invents backend contracts that do not exist

Implications:

- all geometry mutation goes through backend round-trips
- missing backend features are hidden or disabled explicitly

## Backend Contracts

### Mission Overlay Payload

The widget consumes mission overlays from the backend Mission surface.

The durable payload concepts are:

- `mission_id`
- `status` — runtime state only (`approved` as the steady-state default,
  `executing` / `armed` when the controller has the mission; legacy
  approval-flavored values may still appear on missions touched by the AI
  planning graph until ADR 0022 follow-up removal lands)
- `goal`
- `waypoint_count`
- overlay `bounds`
- route-line and waypoint features

The backend overlay builder remains the source of truth for exact field shape.
There is no separate revision resource; all frontend code keys off
`mission_id`.

### Coordinate System

Mission overlay points are local scene metres `{x, y, z}`, not WGS84
lat/lon.

Design rule:

- scene-mode rendering uses `L.CRS.Simple`
- WGS84 export remains a server-side concern
- any future WGS84 basemap mode must be a distinct widget mode with explicit
  CRS metadata

### Mission List

Durable target: one row = one Mission, with the independent **Visible**,
**Selected**, and **Active** states from ADR 0021.

Design rules:

- clicking a row makes that Mission Active and Visible
- hiding the Active Mission clears Active
- executing missions remain force-visible
- AI clone-and-edit produces a second row rather than mutating the source row

### Execution

The widget uses existing backend transitions rather than inventing new ones.

Design rules:

- per [ADR 0022](../../../cross-cutting/decisions/0022-drop-operator-approval-gate.md),
  Missions carry no operator-facing approval state; every row is immediately
  playable
- execution is an explicit action (operator `▶` button in Strict, banner
  click in Confirm, AI tool call in Autonomous) with controller-version
  staleness checks
- after execution, the widget refreshes mission and overlay state

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

Each Mission row carries:

- visibility control
- status indication
- vehicle/profile identity
- mission name or equivalent label
- origin indicator
- action affordances appropriate to the revision state

Behavior rules:

- visibility is per-row and uncapped (per ADR 0021 § 4, Visible is 0..N); the
  widget does not silently hide missions to "avoid clutter"
- focus dims non-focused visible missions
- fit-to-bounds runs only on the widget's first non-empty load; subsequent
  visibility toggles, selection changes, focus changes, and in-place edits
  must not pan or zoom the map. Re-fit is an explicit user action only.
- numbered waypoint badges remain visible because color alone is insufficient
- the sidebar header exposes a settings affordance that deep-links to
  `Settings → Mission Lifecycle` (`/settings?tab=mission-lifecycle`) in a new
  browser tab, per [ADR 0021 §6](../../../cross-cutting/decisions/0021-mission-lifecycle.md)

## Selection State

Selection is a shared concern between the sidebar and the map. To avoid
threading callbacks through every layer, selection lives in a pure store
mirroring the `editState.js` pattern.

Design rules:

- A `selectionState` module holds `{ activeMissionId, selectedMissionIds: Set,
  anchorMissionId }`. DOM- and Leaflet-free. Subscribable.
- Both the sidebar and the map read and write through the store; neither
  component owns the truth.
- The `anchorMissionId` records the last plain-clicked row for shift-range
  semantics. It updates on plain click only; shift- and cmd-clicks do not move
  the anchor.
- Activating a mission keeps that mission in the selection (active is always
  ∈ selection). Single-click sets the selection to `{ id }`.
- The store is intentionally minimal — it does not persist across reloads.

Modifier-key handling is defined once in the row-click handler and reused by
the map's polyline/waypoint click handler; it is not redefined per surface.

## Map View Controls

The widget owns a small Leaflet control mounted top-right of the map. The
control hosts an icon row that is data-driven so individual buttons can be
added, reordered, or removed without restructuring the control.

Current buttons:

- **Fit to scene** — returns the viewport to scene bounds from the existing
  scene metadata path.
- **Fit to selection** — fits to the bounding box of
  `selectionState.selectedMissionIds`; falls back to the active mission when
  the selection size is ≤ 1. Bound to `f` while focus is inside the widget.
- **Style switcher** — opens a popover offering terrain, scene image, and
  plain grid. The choice persists in `localStorage` under a single key.

The widget applies hard clamping at construction:

- `setMaxBounds(sceneBounds)` so panning cannot leave the scene.
- `minZoom = fitZoom`, where `fitZoom` is the zoom level at which scene
  bounds fill the viewport. The "Fit to scene" button is the return
  affordance.

Auto-fit-on-activate is intentionally not implemented; the user invokes fit
explicitly. This avoids jarring view changes mid-edit.

## Map Rendering Rules

- non-executing missions render solid
- executing missions render as locked
- completed or otherwise-superseded missions render dimmed
- selected missions render at full opacity; unselected (but visible) missions
  render dimmed (≈0.6); the active mission carries an additional 1–2 px
  stroke bump over its selected styling. Selection and active are two
  channels collapsed into the existing colour + stroke system without new
  glyphs or halos
- fit-to-bounds (initial-load only, per Mission List Rules) uses the focused
  mission when one exists, else the visible-set union

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

- editing is available only for non-executing missions
- gesture handlers short-circuit on locked missions
- client edits operate against backend-backed mission state with optimistic
  concurrency checks
- manual edits mutate the active Mission in place
- AI edits default to clone-and-edit, producing a new Mission row
- only `executing` missions are locked; all other statuses are directly
  editable without a fork prompt. The fork flow (with confirm dialog and
  source-hiding from `_visibleMissionOrder`) is still triggered when
  `LOCKED_STATUSES` fires, but that set currently contains only `executing`.

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

### Hard Lock During Execution

While a mission is executing (or armed):

- edit affordances are disabled
- drag/insert/delete gestures are blocked before state changes
- mission-level delete is rejected by the backend with HTTP 409 when the
  controller has the mission in `executing` or `armed` state; the widget must
  not present delete as available on such a row
- the mission remains visibly locked in both the list and map rendering

### Delete And Undo

- Deletes are **soft**: the backend sets `deleted_at` on the row instead of
  removing it. `MissionRepository.list` filters out soft-deleted rows; `get`
  hides them by default. `#index` is never reused, per ADR 0021 § 2.
- `POST /api/ai/missions/{id}/restore` flips `deleted_at` back to `NULL`.
- The widget surfaces undo via a toast with an "Undo" button after each
  successful delete; the operator is not interrupted by a confirm dialog.
- Hard purge of soft-deleted rows is deferred — there is no automatic
  reaper yet.

## Mission Colour

Each mission has an identity colour stored in the `missions.color` column
(migration 013) and exposed in every API row response. The colour follows the
mission across browsers, sessions, and export/import.

Design rules:

- Color is assigned at creation time:
  `_MISSION_COLOR_PALETTE[mission_id % len(palette)]` in
  `gcs_server/ai/mission_repository.py`. The palette is a curated 24-colour
  set biased away from terrain-blending greens; only a small number of greener
  options remain, and those skew toward brighter teal/lime tones so routes stay
  readable over the default map.
- Existing rows with an empty `color` column receive the same deterministic
  fallback when read.
- User overrides are persisted via `PATCH /api/ai/missions/{id}/color`. The
  picker sends this call on commit.
- `↺ Reset` persists the mission's deterministic palette default back through
  the same `PATCH` path; it is not a client-only preview clear.
- `missionColorOverrides` (the prior `localStorage` fallback) is removed. `assignPaletteColor` is removed.
- The sidebar row consumes the mission colour beyond the 4 px chip: the title
  plus vehicle/origin identity icons use the same colour token so a committed
  change is visible in the mission item itself.
- State-channel indicators (edit-mode stripe, selection dimming, active stroke bump) never reuse the identity colour and are not stored alongside it.

## Mission List Sort, Import, and Export

These are sidebar surfaces, but their implementation lives next to the
widget:

- Sort options are defined in a single config array consumed by the dropdown
  and by the underlying comparator factory. Adding, renaming, or reordering
  options is a one-line change.
- Sort choice persists in `localStorage` under a single key. The default is
  Updated date (newest first).
- Import/export speak JSON only this cycle. Single-object and array inputs
  are both accepted on import; output mode (active / selection / all visible)
  drives the shape.
- Export strips `id`, `status`, `client_version`, timestamps, and audit
  fields before emit. Import strips any incoming `id` and timestamps, sets
  `status = planning` (or the lowest writable status), and uses
  all-or-nothing validation on batches.
- Import/export entry points share one overflow `⋯` menu in the sidebar
  header; menu items live in a config array.

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
