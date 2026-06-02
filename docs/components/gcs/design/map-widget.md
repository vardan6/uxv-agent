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

### Layout and Sizing

The `.ai-map-area` panel carries `width: 100%` **and** `aspect-ratio: 4/3`. Both
must be present. `width: 100%` is load-bearing: without it, setting an inline
`height` via the bottom-drag resizer causes `aspect-ratio` to re-derive the width
from the new height (e.g. `600px × 4/3 ≈ 800px`), producing a narrower card than
the chat section above. `width: 100%` pins the horizontal size to the container;
`aspect-ratio` is then only active on initial load (no inline height yet).

The mission list sidebar is resizable: `.map-widget-shell` uses
`grid-template-columns: var(--map-list-width, 280px) 8px 1fr`. An 8px
`.map-list-resizer` splitter button sits between the list and the map canvas,
wired in `MapWidget._bindListResizer()`. Width is persisted to localStorage under
`gcs-map-list-width` (range 180–480 px, default 280 px). On ≤980 px screens the
splitter is hidden and the shell collapses to a single-column stacked layout.

## Mission List Rules

Each Mission row carries:

- a **status stripe** (4 px left edge) coloured by the active revision's status,
  plus a matching **status label**
- a **visibility control** (eye toggle) and a **selection checkbox**
- a **colour chip** that doubles as a button — clicking it opens the per-Mission
  colour picker (see *Mission Management Affordances*)
- **vehicle/profile identity** — a per-row vehicle icon driven by the Mission's
  `vehicle_profile_id`
- the **mission name** (inline-renamable on double-click; an untitled Mission
  gets a deterministic auto-number) and a **created-at** date in the row meta
- a **provenance/origin indicator** — 👤 manual / 🤖 ai / ✏️ ai+edited (a Mission
  whose AI proposal was operator-modified)
- **action affordances** appropriate to the active revision's status: an
  **edit ⇄ done** toggle, the legacy ▶ linear-plan upload, a 🗑 delete, and a 🔒
  lock when executing. `approve`/`reject` stay off the row (ADR 0021)

Behavior rules:

- the whole row is clickable to promote the Mission to Active+Visible; modifier
  clicks (shift / meta / ctrl) extend the Selected set. Inner controls
  (checkbox, eye, edit, execute, delete, rename) stop propagation so they don't
  double-fire, and inline rename (dblclick) keeps working alongside row-click
- visible overlays are capped softly to avoid clutter
- focus applies fit-to-bounds and dims non-focused visible missions
- numbered waypoint badges remain visible because color alone is insufficient
- every operator- or AI-derived value interpolated into row markup is escaped
  (`escapeHtml`) before it reaches `innerHTML`; list state stays **mission-keyed**
  (active revision id/status, `#index`), never revision-keyed

## Mission Management Affordances

Beyond per-row editing, the list offers Mission-management UX:

- **Per-Mission colour override** — a colour picker (swatch grid + custom hex +
  reset, with live hover-preview that re-renders the map in the candidate
  colour). Resolution order is **override (if set) → automatic palette**
  (`assignPaletteColor`, keyed on visibility order). Overrides persist client-side
  (localStorage, keyed by Mission id) and layer above the auto palette without
  breaking the soft visibility cap.
- **Sort** — a persisted (localStorage) sort preference over the list: Updated
  newest · Created newest · Status · Label A–Z · Selected first · Visible first.
- **Overflow `⋯` menu** — a header menu hosting the sort options and **JSON
  import / export**. Export serialises the visible/selected Missions to a JSON
  blob; import creates one flat Mission per entry through the standard create
  path (not a revision payload).
- **Bulk actions** — the selection batch bar carries Show / Hide / Clear **and
  bulk Delete** (delete loops the per-Mission delete, honouring the
  executing → 409 guard, then refreshes once).

Design decisions (the management suite is ported forward from `e4a7c61`
additively — it predates the current flat-Mission/`escapeHtml` rewrite):

- the control cluster (view-mode, layer toggles, fit buttons, info bar) lives
  **top-right**, clear of the Leaflet zoom ± — the branch's own richer view-mode
  cluster is *relocated* there rather than importing `e4a7c61`'s narrower
  `MapViewToolbar`
- bulk delete *extends* the existing batch bar rather than importing a second
  bulk-action bar
- selection stays in the widget's own selection state; no separate selection
  store is reintroduced
- `vehicle_profile_id` and a per-Mission provenance summary must be added to the
  `list_missions` payload before the vehicle icon and ✏️ badge can render — those
  are the only backend additions; every other affordance above is frontend-only

## Map Rendering Rules

- proposed revisions render dashed and visually weaker
- approved revisions render solid and fully emphasized
- executing revisions render as locked
- superseded or completed revisions render dimmed
- fit-to-bounds uses the focused mission when one exists, else the visible-set
  union; scene bounds are the final fallback so the 3d-env map stays centered
  with no missions focused
- auto-fit fires only when the logical fit-target changes (`_lastFitKey`), **not**
  on every poll tick — the view must not snap back every 5 seconds while the
  user is panning
- `setFocus` always resets `_lastFitKey` so switching mission focus immediately
  re-fits to that mission's bounds
- the "No missions yet" empty-state overlay is suppressed when the scene is
  loaded (`_sceneBounds` known) — terrain + objects IS content; the overlay must
  not cover it

Scene-mode layers (CRS.Simple, `/api/replay/scene-map` payload):

- `TerrainCanvasLayer` — heightmap gradient canvas, z-index 180; `setVisible(v)`
  uses `setOpacity(0 / original)` to avoid re-rendering
- `SceneObjectsLayer` — roads (polylines) and object rectangles (per-kind color)
  + spawn marker in **separate sub-groups** (`_roadsGroup`/`_objectsGroup`);
  drawn on `scenePane` (z-index 300, between terrain and missionPane 470). Ported
  from the replay page; tooltip shows label + model_ref. `setRoadsVisible(v)` and
  `setObjectsVisible(v)` toggle each sub-group's SVG element `display`
- `GridLayer` — 50m coordinate grid ported from the replay page; `setVisible(v)`
  toggles each polyline's element `display`
- `MissionOverlayLayer` — mission paths and waypoints on `missionPane` (z-index
  470)

Status (2026-06-01): scene parity with the replay page is implemented and
syntax-verified. Two bugs were found and fixed during first attempted browser
test (never browser-verified before this):
1. `map-widget-empty` (`position:absolute; inset:0; background:80% opaque;
   z-index:500`) was covering terrain+objects when no missions existed — fixed by
   suppressing it when `_sceneBounds` is set.
2. `_fitBounds` was called inside `_render()` (5-second poll cycle), resetting
   pan/zoom on every tick — fixed with `_lastFitKey` guard.
**Browser smoke still pending** — start the server, open `/ai`, confirm terrain +
objects render and view auto-fits to scene bounds with no mission focused.

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

## Scene Toolbar (Phase 7 — in progress)

The map panel needs a toolbar matching the replay page's controls.

**Layer toggles** — implemented (2026-06-01). Four checkboxes in a
`.map-layer-toolbar--overlay` pill wired into `MapWidget._onLayerToggle`. Each
toggle is local state, reset on load; applied to layers via
`setVisible`/`setRoadsVisible`/`setObjectsVisible` after async scene load.
Mission-overlay layers are never toggled from this bar — they are controlled by
the mission list's Visible state.

**Toolbar placement** — the whole control cluster (layer toggles, view-mode
selector, fit buttons, basemap toggle, info bar) sits **top-right**, clear of the
Leaflet zoom ± in the top-left. The first browser smoke (2026-06-02) found the
original top-left placement collided with the zoom buttons and hid the fit
buttons; relocating right matches the replay page and resolves both.

Design rules (still applicable to remaining items):

**Fit-bounds buttons** — three explicit buttons in the toolbar: Fit Scene (fits
`_sceneBounds`), Fit Mission (fits the focused mission overlay bounds), Fit All
(fits the visible-mission union). These reset `_lastFitKey = null` so the next
`_render` re-fires `_fitBounds`. Disabled when the target bounds are unknown.

**View mode selector** — dropdown with three options: Virtual Terrain (default;
heightmap gradient + objects), CAD/Object View (objects only, solid background),
Heightmap (raw greyscale elevation). Mode change reconstructs or reconfigures the
scene layers in place; mission overlays are unaffected. The replay page's
"GPS/Satellite Debug" mode maps to the existing Basemap toggle (WGS84 OSM panel).
View mode and the basemap toggle are **independent**: switching to CAD/Object
View must not tear down the basemap/satellite view (a parity bug found in the
2026-06-02 smoke).

**Cursor/info bar** — fixed bar at the bottom of the map canvas. Left slot: cursor
scene-metre coordinates (`x: N m, y: N m`), with WGS84 equivalent in parentheses
when the focused mission has a known origin datum. Right slot: selection detail
(waypoint index, provenance, altitude) when a waypoint is selected; otherwise
shows mission/scene summary. Sourced from Leaflet `mousemove` + `editState`.

## Scene-Mode Manual Mission Creation (Phase 7 — planned)

The `➕ New mission` flow (requirements §Mission CRUD) must work in scene-mode
(CRS.Simple), not only via the basemap draw tools.

Design rules:
- `➕ New mission` creates a blank Mission via backend, promotes it to Active, and
  enters `editState.editMode = 'add'` — the existing `map click → insertWaypoint`
  path already handles placement once `add` mode is active
- this is distinct from the Basemap Corridor/Survey tools: those generate a whole
  pattern server-side from drawn WGS84 geometry; scene-mode add is click-to-place
  individual waypoints in local metres
- the `➕ New mission` button lives in the `MissionListPanel` header (an empty list
  already shows a call-to-action area)

## Deferred Beyond The Current Widget Contract

These stay outside the core widget contract until real backend/platform support
exists:

- edit-during-execution
- richer per-waypoint property schema editing
- floating/second-monitor window behavior beyond re-parenting support
- full replay-page migration onto `MapWidget` (telemetry path replay, playback
  controls, Follow Rover nav mode) — the scene render layers are already ported;
  the dynamic replay-session path is what remains
