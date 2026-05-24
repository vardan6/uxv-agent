# Map Widget

Authoritative design and implementation brief for the vehicle-aware, reusable map widget that ships first on the AI chat page (`/ai`) and later replaces the monolithic Leaflet code in `replay.html` / `replay.js`. This document records target UX, phase boundaries, and backend contracts. Event wiring and some endpoint shapes remain implementation-plan inputs and are listed in **Open Questions**.

Tracking epic: [issue #5](https://github.com/vardan6/remote-rover/issues/5) (this doc supersedes the issue body where they diverge).

Review history: `docs/archive/gcs/2026-05-20-map-widget-codex-review.md` (review that drove the v2 revision; archived after findings were incorporated into this doc).

---

## Purpose

Operators today approve agent-proposed missions on the AI chat page **without spatial review** — the only existing Leaflet map lives on the replay page as a 3500-line monolith that cannot be reused. Backend mission overlay APIs exist but no frontend renders them. This is a known safety gap; the mission approval and execution boundary now lives in [`../../ai-agent/requirements.md`](../../ai-agent/requirements.md) and [`../../ai-agent/design.md`](../../ai-agent/design.md).

Goal: give the operator spatial review of agent proposals on `/ai` quickly via a small read-only render slice, then grow toward multi-mission management and (eventually) direct-manipulation editing — but only after the backend has the contracts to support those steps safely.


## Current Implementation Reality

Updated 2026-05-22 to reflect Phases 1A–1E complete.

**Frontend (`gcs_server/static/map/`):**
- `MapWidget.js` — orchestrator; mounts Leaflet map, manages polling, action callbacks, confirm modal, vehicle layer, edit session, keyboard shortcuts
- `layers/MissionOverlayLayer.js` — renders route polylines and numbered waypoint badges; `renderEditable()` draws draggable markers, ghost midpoint inserts, and provenance badges (`👤` / `✏`) for the active edit session
- `layers/LiveVehicleLayer.js` — subscribes to `/ws`, draws heading-rotated vehicle arrow marker
- `ui/MissionListPanel.js` — grouped revision list; visibility/focus toggles; approve/reject/execute action buttons; 🔒 badge for executing state
- `ui/SelectionPanel.js` — read-only waypoint inspector shown on marker click; displays index, x/y/z coords, and provenance label
- `ui/ContextMenu.js` — right-click context menu on waypoint markers: Insert before, Insert after, Delete, Move to vehicle position (shown only when vehicle telemetry is available)
- `ui/KeyboardHelpOverlay.js` — `?` key keyboard shortcuts dialog
- `state/editState.js` — pure in-memory store (no DOM/Leaflet): selection set, editMode (`null | 'vertex' | 'add'`), waypoints with provenance, `clientVersion`, `busy`; `isEditable()` blocks when status is `executing`
- `data/missionApi.js` — wrappers for all mission overlay, list, approve, reject, execute, and controller-state endpoints
- `data/missionMutationApi.js` — wrappers for the four Phase 1D mutation endpoints plus `getRevision`
- `data/vehicleProfileApi.js` — vehicle profile wrappers
- `missionListLogic.js` — pure grouping, visibility cap, palette assignment
- `vehicleProfiles.js` — client mirror of the seven-field `VehicleProfile`
- `ai.html` — mounts `MapWidget` on `ai:session-open` and `ai:session-refreshed` events; reads session id via `window.__aiGetActiveSessionId`

**Phase 2 items now implemented:**
- `ui/HintToasts.js` — transient hint toasts (auto-dismiss); shown on drag-start to hint "Hold Alt to snap"
- Marquee multi-select — drag on empty map (while a revision is loaded, non-add mode) rubber-band selects waypoints via capture-phase mousedown intercept
- Alt-snap — hold Alt during waypoint drag to snap to the nearest other waypoint within 12 px screen distance
- Execute recovery hardening — `MapWidget` now handles backend `stale_revision` and `stale_controller_version` responses by refreshing state, refocusing the active revision, and updating cached controller version from the backend response

**Phase 2 elevation profile implemented (2026-05-23):**
- `data/terrainApi.js` — `fetchSceneMap()` hits `GET /api/replay/scene-map`; `makeSampler(sceneMap)` returns bilinear interpolation over the 128×128 normalized heightmap
- `ui/ElevationProfilePanel.js` — SVG chart: terrain fill, route altitude polyline, clearance fill, numbered waypoint dots; status chip: ✓ CLEAR / ⚠ LOW CLEARANCE / ⚠ BELOW TERRAIN; minimum clearance dashed line for aerial vehicles (multirotor 3 m, fixed_wing 5 m); collapsible; dot click selects waypoint in edit state
- `MapWidget.js` — elevation panel mounted below the shell; updates on `_render()`, on edit-state change (live drag feedback), and on edit-session end; terrain sampler loaded once via `fetchSceneMap()` at mount time

**Phase 2 bulk-edit action bar implemented (2026-05-23):**
- `ui/BulkEditActionBar.js` — floating bar shown when ≥2 waypoints are selected (editable revision only); shows selection count, altitude bulk-set (sequential `PATCH` per waypoint, median z pre-fill, Enter submits), delete-all-selected button, and clear-selection button; auto-hides on single-select (defers to SelectionPanel) and when edit is not active

**Phase 2 terrain canvas layer implemented (2026-05-24):**
- `layers/TerrainCanvasLayer.js` — Leaflet `imageOverlay`-backed terrain layer; bilinear colour palette (4-band green→tan→grey); creates a `terrainPane` at z-index 180 (below mission overlays at 470); `addTo(map)` / `remove()` / `setOpacity()` interface; mounted in `MapWidget.mount()` immediately after `fetchSceneMap()` resolves

**Not yet implemented (Phase 2):**
- `layers/GeofenceLayer.js` — blocked on backend geofence API (no source exists)
- "Set as home" context menu item (no backend contract yet)

**Backend routes that exist (verified):**
- `GET /api/ai/mission-revisions?session_id=...` — list revisions
- `GET /api/ai/mission-revisions/current?session_id=...` — current revision
- `GET /api/ai/mission-revisions/{revision_id}` — single revision
- `GET /api/ai/mission-revisions/{revision_id}/overlay` — overlay payload for a specific revision
- `GET /api/ai/mission-overlays/current?session_id=...` — overlay for the current revision
- `POST /api/ai/mission-drafts/{draft_id}/approve` — **draft approval; also triggers `.plan` export and revision-side sync**. Supports `execute_after_approval=true` body flag.
- `POST /api/ai/mission-drafts/{draft_id}/reject`
- `POST /api/ai/mission-revisions/{revision_id}/execute` — **execution gate**; takes `expected_controller_version` for staleness checks.
- `POST /api/ai/mission-revisions` — create a new client-authored revision (operation-scoped, inherits provenance from parent)
- `PATCH /api/ai/mission-revisions/{revision_id}/waypoints/{waypoint_index}` — update waypoint geometry; promotes provenance to `ai+edited`; takes `expected_version` for staleness check
- `POST /api/ai/mission-revisions/{revision_id}/waypoints` — insert waypoint at `after_index`; provenance = `user`; takes `expected_version`
- `DELETE /api/ai/mission-revisions/{revision_id}/waypoints/{waypoint_index}` — delete waypoint; takes `expected_version`
- `GET /api/vehicle-profile/active` — returns the active `VehicleProfile` as JSON
- `GET /api/vehicle-profiles` — returns `KNOWN_PROFILES` list
- `GET /api/snapshot` and `WS /ws` — telemetry / snapshot / controller events.

**Backend routes that do not exist (verified):**
- Any standalone `.plan` export route (export currently happens inside draft approval).
- Any geofence API.

**Mission model facts:**
- Operations are the canonical mission group: `ai_mission_operations` has `id`, `active_revision_id`, `status`.
- `ai_mission_revisions` rows carry `operation_id`, `draft_id`, `status`, and the full `mission` JSON.
- The draft system (`MissionDraftService`) and the revision system (`MissionExecutionService`) coexist; approval drives both in sync.
- Overlay coordinates are **local scene metres** `{x, y, z}` from the mission payload — **not lat/lon**. Mission export projects to WGS84 separately for `.plan` files.
- Per-waypoint provenance is now included in overlay waypoint features and persisted in `provenance_json` as `ai` / `user` / `ai+edited`.
- Client-side edit forking must support all current mission waypoint shapes: direct `mission.waypoints`, `route_artifacts[*].waypoints`, and `steps[*].waypoints`. This is now implemented in `MapWidget.collectEditableWaypoints()`.

**Vehicle profile facts:**
- `gcs_server/ai/vehicle_profile.py` defines three profiles: `rover_default` (ground), `quad_x500` (multirotor), `fixed_wing_default` (fixed-wing).
- Each profile has **seven fields**: `id`, `kind`, `mav_vehicle_type`, `planner_kind`, `default_cruise_alt_m`, `supports_yaw_at_waypoint`, `max_speed_mps`.
- These are vehicle **capability** fields, not per-waypoint property schemas. Per-waypoint UI schemas are a new design layer (out of Phase 1).
- `get_active_profile()` always returns `ROVER_DEFAULT` today; settings-driven selection is a separate workstream.

## Non-Goals and Safety Invariants

**Non-negotiable invariants for any phase:**

1. **Approval ≠ execution.** Approving a draft writes the `.plan` and syncs revision state; it does **not** drive the rover. Execution is a separate explicit user action that goes through `POST /api/ai/mission-revisions/{revision_id}/execute` with a controller-version check.
2. **No client-side mutation of executing missions.** When a revision is executing, the widget MUST disable all edit affordances and short-circuit gesture handlers.
3. **The widget never silently overwrites authoritative state.** No client-side optimistic mutation without a backend round-trip.
4. **No fake backend contracts.** If a route does not exist, the widget either does not render the affordance, or renders it disabled with a tooltip explaining why.

**Out of scope across all phases of this document:**
- Replay page migration to `MapWidget`.
- 3D map view, floating window mode, second-monitor popout, foldable rail (re-parenting is a design hook only).
- Snap-to-road routing, edit-during-execution (look-ahead or push-update).
- Settings UI for vehicle-profile selection / auto-detect.
- Frontend test infrastructure (vitest/jest).
- Agent-side honoring of per-waypoint provenance locks (separate AI workstream).

## Phase Plan

Phase 1 shipped in five slices (1A–1E). Phase 2 covers everything requiring new backend sources or new platform contracts.

**Shipped:** Phases 1A–1E are complete as of 2026-05-22. Phase 2 (elevation profile, replay page migration, geofence, bulk-edit) is next.

### Phase 1A — Read-only current mission overlay on `/ai`

**Goal:** below the chat, render a Leaflet map showing the current mission overlay for the active session. No list, no edit, no extra layers.

In scope:
- New `gcs_server/static/map/` module tree (see Frontend Module Boundary).
- `MapWidget` shell using `L.CRS.Simple` (scene-coordinate mode) — matches replay convention.
- `MissionOverlayLayer` consuming `GET /api/ai/mission-overlays/current?session_id=...`.
- Fit-to-bounds using the payload's `bounds`. Handle one-point missions and missing bounds.
- Empty state ("No mission overlay yet.") and error state (non-blocking banner with manual refresh).
- Manual refresh button. No automatic polling yet.

Out of scope for 1A:
- Mission list, revision browsing, multi-mission visibility, vehicle layer, geofence, any edit affordance.

### Phase 1B — Mission revision list with focus/hide

**Goal:** show all revisions for the session in a left panel, group by `operation_id`, support focus and visibility.

In scope:
- `MissionListPanel` driven by `GET /api/ai/mission-revisions?session_id=...`.
- **Grouping algorithm:**
  1. Fetch revisions.
  2. Group rows by `operation_id`.
  3. The operation's `active_revision_id` (falling back to newest revision) is the default visible row.
  4. Earlier revisions live under a `▾ N earlier` expander.
  5. `draft_id` is compatibility metadata, not a grouping key.
- Lazy fetch of per-revision overlays via `GET /api/ai/mission-revisions/{revision_id}/overlay`.
- Eye-icon visibility toggle. Soft cap of **3 visible missions**; the 4th hides the oldest visible. Revisions of operations with status `executing` are force-visible.
- ColorBrewer Set2 palette assigned to visible overlays; color dot in the row doubles as legend.
- Row-click = focus (fit to that mission, dim others to ~25% opacity). Background highlight indicates focused row, separate from status stripe.
- Status stripe colors for: `proposed`, `selected-on-map`, `approved`, `executing`, `completed`, `superseded`.
- Numbered waypoint badges on every visible mission (accessibility — color alone is not sufficient).

Out of scope for 1B:
- Edit, accept, execute, export buttons; vehicle layer; geofence.

### Phase 1C — Wire existing safe transitions (no new mutation APIs)

**Goal:** expose the existing backend transitions through the widget. Reuse current endpoints; do not invent new ones.

In scope and how each maps:
- **Approve draft (does not execute).** Per-row `✓ Approve draft` button. Calls `POST /api/ai/mission-drafts/{draft_id}/approve` with `note` body. Tooltip text MUST be: *"Approve draft (does not execute)."*
  - Side effects (already happens server-side): writes `.plan` via `MissionExportService`, syncs revision via `approve_revision_for_draft`.
- **Reject draft.** Per-row `🗑 Reject` button. Calls `POST /api/ai/mission-drafts/{draft_id}/reject`.
- **Execute revision.** Per-row `▶ Execute mission` button, only enabled on approved revisions. Calls `POST /api/ai/mission-revisions/{revision_id}/execute`. Includes `expected_controller_version` from the snapshot to detect stale state. Tooltip: *"Execute on rover (uploads and starts mission)."* Triggers a confirmation modal (single click is not enough for this verb).
- After any of the three calls, refresh the revision list and the current overlay.
- Live vehicle layer driven by existing `/ws` telemetry. On by default. Tolerates missing or stale telemetry without blocking overlay rendering.

Terminology rules:
- **Do not use "Accept."** Use "Approve draft," "Execute mission," or "Export plan" — each refers to a distinct, separately-gated transition.
- The previous "dashed → solid on accept" visual is mapped to revision `status`:
  - `proposed` → dashed, desaturated, hollow markers.
  - `approved` (post-approve-draft) → solid, filled markers.
  - `executing` → solid, filled, with 🔒 badge on the row and gesture lockout.
  - `superseded` / `completed` → dimmed.

Out of scope for 1C:
- Standalone export route or button (export piggybacks on draft approval today; a dedicated re-export is Phase 2).
- Any geometry mutation, new-mission creation, duplicate, import.

### Phase 1D — Backend mutation API ✓ complete

**Goal:** design and add the minimum backend surface that the editor needs.

Implemented (migration 005 + `MissionExecutionService` methods + routes in `app.py`):
- `POST /api/ai/mission-revisions` — create client-authored revision; inherits provenance from parent.
- `PATCH .../waypoints/{index}` — update waypoint geometry; promotes provenance to `ai+edited`.
- `POST .../waypoints` — insert waypoint; provenance = `user`.
- `DELETE .../waypoints/{index}` — delete waypoint.
- `client_version` column on `ai_mission_revisions` for optimistic concurrency; all mutation routes reject on version mismatch.
- `provenance_json` column carries per-waypoint `ai` / `user` / `ai+edited` state; `_build_mission_overlay_payload` now includes provenance per waypoint feature.

### Phase 1E — Direct manipulation editor ✓ complete

Implemented:
- `state/editState.js` — pure store; selection set, editMode (`null | 'vertex' | 'add'`), waypoints with provenance, `clientVersion`, `busy`, `isEditable()`.
- `ui/SelectionPanel.js` — read-only waypoint inspector: index, x/y/z in metres, provenance label.
- `ui/ContextMenu.js` — right-click context menu on markers: Insert before, Insert after, Delete.
- `ui/KeyboardHelpOverlay.js` — `?` key modal listing all map keyboard shortcuts.
- `data/missionMutationApi.js` — client wrappers for all four mutation endpoints plus `getRevision`.
- `MissionOverlayLayer.renderEditable()` — draggable markers, ghost midpoints for segment insertion (including end-cap ghosts before the first and after the last waypoint for prepend/append), provenance badges.
- `MapWidget` keyboard handler: `V` toggle vertex-edit, `A` toggle add-waypoint (map click appends waypoint in add mode), `F` focus, `Delete`/`Backspace` delete selected, `Esc` close menu → clear selection → exit edit, `?` help.
- Edit banner shows active mode label (`· vertex edit` / `· add mode`) alongside status and revision ID.
- `LiveVehicleLayer.getPosition()` exposes last known vehicle position; used by "Move to vehicle position" context menu item.
- Hard-lock: `LOCKED_STATUSES` set (`executing`, `approved`, `completed`, etc.) disables all edit affordances and shows `not-allowed` cursor.
- Editing a locked but non-executing revision now forks a new client revision from the full canonical waypoint set, not only `mission.waypoints`.
- When edit starts, the target revision is pinned into the visible set, focused, and its operation group is expanded so the operator does not keep looking at an older approved sibling.

Not yet implemented:
- "Set as home" context menu item (no backend contract yet).

Execution hardening added after Phase 1E:
- `MissionListPanel` only shows `Execute` on the operation's active revision. Older executable siblings show a `stale` badge instead.
- Backend `execute_revision()` rejects non-active sibling revisions with `status = stale_revision`.
- `missionApi.executeMission()` preserves structured error payloads on non-200 responses.
- `MapWidget` recovery paths:
  - `stale_revision` → clear overlay cache, refresh, pin/focus returned active revision, show targeted message
  - `stale_controller_version` → update cached `controller_version`, refresh, pin/focus controller active revision when present, show targeted retry message
- `MapWidget._loadControllerState()` now reads `controller_state.controller_version` from the backend payload; the previous `current_version` name was wrong for this API surface

Recommended next continuation from the current codebase:
- planning-shell / mission-execution integration around edited revisions, not more standalone map affordances
- specifically: teach the planning shell to detect and resolve conflicts against operator-edited (`ai+edited`) waypoint provenance and active-revision lineage

### Phase 2 — Out of scope here

- Replay page migration (extract historical-track layer from `replay.js`; rebuild replay on `MapWidget` — `TerrainCanvasLayer` is now extracted).
- Elevation profile panel — **required before the first multirotor mission ships**.
- Floating / pop-out / second-monitor window modes (design hook only — `MapWidget` must support re-parenting via `invalidateSize()`).
- 3D map view.
- Snap-to-road, edit-during-execution.
- Bulk-edit action bar for multi-selected waypoints — **implemented 2026-05-23**.
- Geofence display + waypoint-vs-geofence validation (only after a real geofence backend source exists).
- Settings UI for vehicle profile selection.
- Vehicle property schema layer (per-waypoint speed / hold / action / altitude / yaw / gimbal forms).

## Backend Contracts

### Mission overlay payload (existing, returned by `_build_mission_overlay_payload`)

Returned by both `GET /api/ai/mission-overlays/current` and `GET /api/ai/mission-revisions/{id}/overlay`. Approximate shape:

```json
{
  "available": true,
  "operation_id": "...",
  "revision_id": "...",
  "draft_id": "...",
  "status": "approved",
  "goal": "...",
  "waypoint_count": 3,
  "bounds": {
    "min_x": 0, "max_x": 10,
    "min_y": 0, "max_y": 20,
    "min_z": 0, "max_z": 0
  },
  "features": [
    {
      "id": "...",
      "type": "route_line",
      "label": "Mission route",
      "route_hash": "",
      "waypoint_count": 3,
      "distance_m": 42.5,
      "points": [{"x": 0, "y": 0, "z": 0}]
    },
    {
      "id": "...",
      "type": "waypoint",
      "label": "Waypoint 1",
      "kind": "waypoint",
      "index": 1,
      "point": {"x": 0, "y": 0, "z": 0}
    }
  ],
  "mission_export": {}
}
```

**Source of truth:** `_build_mission_overlay_payload()` and `get_revision_overlay()` in `gcs_server/ai/mission_execution_service.py`. Do not cite line numbers — they drift.

### Coordinate system (critical implementation note)

Mission overlay points are **local scene metres** `{x, y, z}`, **not** WGS84 lat/lon. The widget MUST use `L.CRS.Simple` (matching replay convention). A tile-projected basemap (OSM, satellite) will not align with overlay coordinates without an additional projection step that is NOT part of Phase 1.

Mission export to QGC `.plan` projects local metres to WGS84 inside `MissionExportService`; that projection is a server-side concern and does not bleed into the widget for Phase 1.

If a future phase introduces a WGS84 basemap mode, it MUST be a distinct widget mode (constructor option), and overlays MUST carry coordinate-system metadata so they can be rendered in the correct CRS.

### Mission revision list (existing)

`GET /api/ai/mission-revisions?session_id=...` returns the list. Each row includes operation join columns (`operation_active_revision_id` etc.) — see the `list_revisions` SQL in `mission_execution_service.py`. Group client-side by `operation_id`. Implementer should verify whether `session_id=""` means "global" or "current session" before defaulting.

### Approval / execution / export

- Approval: `POST /api/ai/mission-drafts/{draft_id}/approve` — body `{ "note": "...", "execute_after_approval": false, "expected_controller_version": <int|null> }`. Side effect: triggers `MissionExportService().export(draft)` and `approve_revision_for_draft(draft_id, ...)`.
- Reject: `POST /api/ai/mission-drafts/{draft_id}/reject`.
- Execute: `POST /api/ai/mission-revisions/{revision_id}/execute` — body `{ "expected_controller_version": <int|null> }`.

The widget does NOT add a separate `/accept` route. The widget does NOT add a standalone export route in Phase 1.

### Vehicle profile (to be added in Phase 1B or 1C)

New routes required:
- `GET /api/vehicle-profile/active` → returns the active `VehicleProfile` dataclass as JSON (seven fields).
- `GET /api/vehicle-profiles` → returns `KNOWN_PROFILES` so the client can render rows whose mission is bound to a non-active profile.

Until these routes exist, the widget defaults to the rover profile and logs a warning. No blocking dialog.

### Telemetry source

Live vehicle position is read from the existing `WS /ws` stream (telemetry / snapshot / controller events). The widget does NOT open a parallel telemetry channel. Fallback if `/ai` does not already open `/ws`: poll `GET /api/snapshot` every 2 s.

### Mission revision push (deferred)

Phase 1 does NOT add a `mission_revision` event on `/ws`. The widget refreshes on:
- AI session load.
- After any user-initiated approve/reject/execute call.
- Optional short polling on `/api/ai/mission-overlays/current` (5 s default, configurable, disabled when tab not visible).

A push event is a Phase 2 follow-up once the read-only widget proves useful.

### Geofence (deferred)

No backend source exists. Geofence display, the `GeofenceLayer`, and waypoint geofence validation are all Phase 2, gated on a real source (MAVLink fence params, config file, or PRD-driven new service).

## Frontend Module Boundary

Vanilla ES modules, no framework, no build step. Leaflet 1.9.4 (CDN, mirroring `replay.html`).

```
gcs_server/static/map/
  MapWidget.js          # orchestrator
  index.js              # barrel re-export
  layers/
    MissionOverlayLayer.js
    LiveVehicleLayer.js
    # Phase 2: GeofenceLayer.js, TerrainCanvasLayer.js, HistoricalTrackLayer.js
  ui/
    MissionListPanel.js
    SelectionPanel.js       # Phase 1B+: read-only waypoint inspector
    HintToasts.js
    KeyboardHelpOverlay.js  # Phase 1E
  data/
    missionApi.js
    vehicleProfileApi.js
    vehicleStateApi.js      # wraps /ws subscription
  state/
    editState.js           # Phase 1E (pure store; no DOM/Leaflet)
  missionListLogic.js      # pure: grouping, visibility cap, palette assignment
  vehicleProfiles.js       # client mirror of seven-field VehicleProfile
  geofenceCheck.js         # Phase 2
```

### Constructor

```js
new MapWidget(container, {
  sessionId,
  vehicleProfileId,   // optional override; otherwise active-profile API
  layers: {           // all optional, default true where supported
    missionOverlay: true,
    liveVehicle:    true,
    geofence:       false,   // Phase 2
  },
  crs: 'simple',      // 'simple' | 'wgs84' (Phase 1 = 'simple' only)
  onEvent,            // callback for {type: 'approval-succeeded', ...} etc.
});
```

Methods: `mount()`, `destroy()`, `invalidateSize()`, `setFocus(revisionId)`, `refresh()`.

### Deep modules (pure, testable later)

- `editState` — selection set, dirty waypoints, provenance map, status. Phase 1E.
- `missionListLogic` — `groupRevisionsByOperation`, `enforceVisibilityCap`, `assignPaletteColor`. Phase 1B.
- `vehicleProfiles` — `getProfile`, `propertySchema` (stub in 1B; real in 2), `isAerial`. Phase 1B.
- `geofenceCheck` — Phase 2.

These are written test-friendly (no DOM/Leaflet imports) so a future test runner can pick them up without refactoring.

## AI Chat Integration

- Map area is a new `<section id="ai-map-area">` appended to the chat shell in `ai.html`. The chat above remains the primary surface; the operator scrolls down to reveal the map.
- Within the map area: list panel on the left, map on the right (CSS grid).
- Re-parenting support: `MapWidget` does not assume its container is at a fixed DOM position. `invalidateSize()` after any container move (placeholder for future floating-window / rail modes).

## Mission List Rules

- One top-level row per `operation_id`. Default visible revision = `operation.active_revision_id` ?? newest revision.
- Earlier revisions under `▾ N earlier` (one-click expand/collapse, persisted per-operation in `localStorage`).
- Row fields:
  - Eye toggle (👁 / 🚫)
  - Status stripe (left edge, six colors)
  - Vehicle icon (🚙 / 🚁 / ✈️) driven by mission's bound profile
  - Mission name + revision count
  - Origin badge (🤖 / 👤 / ✏️ — populated as backend exposes provenance; until then, all rows show 🤖 for agent-created and `null` for the rest)
  - Color dot (palette color when visible)
  - Action icons (depends on phase — see Phase 1B/1C)
- Soft cap: 3 visible overlays. The 4th eye-on toggles off the oldest visible.
- Executing revisions are force-visible.

## Map Rendering Rules

- CRS: `L.CRS.Simple` (Phase 1).
- Proposed revision: dashed polyline (`dashArray: '6,6'`), desaturated palette color, hollow `circleMarker` waypoints.
- Approved revision: solid polyline, full palette color, filled `circleMarker` waypoints.
- Executing revision: solid + filled + 🔒 overlay badge on the polyline midpoint.
- Superseded / completed: dim to 35% opacity.
- Every waypoint marker has a `L.divIcon` number badge with the mission's palette color background.
- Focused mission: full opacity. Non-focused visible missions: 25% opacity.
- Fit-to-bounds uses the focused mission's `bounds`; if none focused, union of visible missions; if none visible, no fit.

## Accessibility and Keyboard Ownership

The map shares a page with a keyboard-heavy chat composer. The widget MUST follow these focus rules:

- Every icon button has an explicit `aria-label` in addition to `title`. Emoji-only buttons are insufficient.
- Status stripe and palette colors are paired with text labels / number badges respectively. Color alone never carries information.
- The widget only listens to keyboard shortcuts when `document.activeElement` is inside the map widget's DOM root (or one of its child inputs that is not a free-text field).
- `/`, `Delete`, `Backspace`, `Esc`, `Enter`, `N`, `A`, `V`, `F` MUST NOT fire while the chat composer, the mission-list search input, or any property-field input is focused.
- `Esc` behavior is ordered: close any open menu/modal, then clear map selection, then exit edit mode.
- Tooltip hover delay: 400 ms. Tooltip format: `"<Action> (<Hotkey>)"`.
- Touch / mobile: list panel + read-only map + buttons MUST be usable. Drag editing MAY degrade to read-only on touch.

## Empty / Error / Offline States

- **No mission overlay available:** center on `(0, 0)` in scene mode, list shows a single CTA card *"No missions yet. Ask the agent."* (`➕ New mission` affordance available via the editor.)
- **Overlay API failure:** non-blocking banner at top of map area: *"Mission overlay unavailable — retrying in 5 s."* Manual refresh button. Map still pans/zooms.
- **Vehicle telemetry failure / no `/ws`:** live vehicle marker hides. Mission overlay rendering is unaffected.
- **Active-profile API missing:** widget uses `rover_default` and logs a console warning. No blocking dialog.

## Editing Model (Phase 1E — Implemented)

Core editing is live. Items still pending are noted inline.

### Gestures

- **Click waypoint body** → select. Shift-click extends, Cmd/Ctrl-click toggles. Marquee-drag on empty map = multi-select.
- **Drag waypoint** → move. **Alt-drag** = snap to nearby waypoints within ~12 px.
- **Click ghost midpoint** → insert real waypoint. **Double-click any segment** = equivalent insert (QGIS power-user idiom).
- **Drag the route polyline** (not at a vertex) → "transitional waypoint" born at drop point (Google Maps directions pattern).
- **Right-click waypoint** → context menu: Insert before, Insert after, Move to vehicle position, Set as home, Delete, Detach from AI proposal.
- **Right-click empty map (not in edit mode)** → no-op (use `➕ New mission` explicitly).

### Keyboard

| Key | Action |
|---|---|
| `Delete` / `Backspace` | Delete selected waypoint(s) |
| `Esc` | Clear selection / exit edit mode (per ordering rule above) |
| `Enter` | Submit pending edit / confirmation |
| `Alt` (during drag) | Snap to nearby waypoints |
| `Shift` (click) | Extend selection |
| `Cmd` / `Ctrl` (click) | Toggle selection |
| `[` / `]` | Step to prev / next waypoint |
| `A` | Toggle add-waypoint mode |
| `V` | Toggle vertex-edit mode |
| `F` | Focus on selected mission |
| `?` | Open keyboard help overlay |
| `/` | Focus mission search input |
| `N` | New mission |

### Provenance state machine

Per-waypoint provenance: `ai`, `user`, `ai+edited`. Once a waypoint is `ai+edited`, agent regenerations MUST diff and ask before changing it (enforced server-side; widget visualizes the lock with the ✏️ badge).

Per-mission origin badge:
- 🤖 = all waypoints `ai`
- 👤 = mission created by user
- ✏️ = mission was AI-generated but at least one waypoint is `ai+edited`

### Hard-lock during execution

While `status == executing`:
- Edit / Reject / Approve buttons disabled with 🔒 badge.
- Gesture handlers (`mousedown` on waypoints, ghost dots, polyline drag) short-circuit before any state change.
- Cursor over the executing mission shows `not-allowed`.
- The agent can still propose new revisions; they appear as separate `proposed` rows under the same operation.

## Acceptance Criteria

Manual QA, per repository convention (no JS tests added by this work).

### Phase 1A

- AI chat page renders a map below the chat without breaking chat layout, even at narrow viewport widths.
- With no mission overlay available, the widget shows the empty CTA card and no Leaflet errors in console.
- With a current overlay available (rover in sim, mission proposed via the agent), route polyline and numbered waypoint markers render in scene coordinates.
- Fit-to-bounds uses the overlay's `bounds` and renders correctly for a one-waypoint mission.
- Stopping the overlay endpoint (e.g. server restart) surfaces a non-blocking banner with a manual refresh that succeeds when the server is back.
- The replay page is unchanged.
- The widget exposes no edit controls.
- No keyboard shortcut steals focus from the chat composer.

### Phase 1B

- Revisions for the active session appear in the left panel, grouped by `operation_id`.
- The default visible row per operation is the one with `id == operation.active_revision_id` (or newest revision if `active_revision_id` is missing).
- Toggling an eye renders or hides the corresponding overlay on the map. The 4th eye-on hides the oldest visible.
- An executing revision is force-visible and its eye is disabled.
- Row-click focuses (fits + dims others to 25%). Background highlight indicates focused row.
- Numbered waypoint badges are present on every visible mission and remain legible at zoom out.
- Status stripe colors match the six documented states.
- No edit affordance is present.

### Phase 1C

- "Approve draft" button calls the existing approve endpoint and tooltip reads *"Approve draft (does not execute)."*
- After approval, the revision row transitions from dashed/proposed to solid/approved.
- "Execute mission" is only enabled on approved revisions, opens a confirmation modal, and sends `expected_controller_version`.
- A failed execute call (stale controller version, controller unavailable) renders a non-blocking error and does not change UI state optimistically.
- "Reject" calls the reject endpoint and removes the row from the list (or marks superseded if backend behavior dictates).
- Live vehicle marker is on by default, updates from `/ws`, and missing telemetry does not block mission overlay rendering.

Phase 1D and 1E shipped without a formal acceptance-criteria section in this doc; the implementation is the record. Phase 2 acceptance criteria will be authored here when the Phase 2 design is concrete.

## Open Questions

Implementation-time questions that the implementer MUST resolve before code, in priority order:

1. **`list_revisions(session_id="")` scope.** Does the empty string mean "global" or "current"? Read `MissionExecutionService.list_revisions` SQL and document the choice. The widget should default to a real session id when known.
2. **`active_revision_id` falsy semantics.** If null/empty, is it valid for an operation to exist without an active revision? Pick the newest revision as the default visible row in that case; verify the column convention.
3. **Coordinate-system claim for the agent.** When the agent proposes a mission, are the points emitted in scene metres or some other frame? `_collect_waypoints` reads them straight from the mission JSON — confirm the upstream producer.
4. **Approve-then-execute UI flow.** The approve endpoint supports `execute_after_approval=true`. Should the widget offer a single "Approve and Execute" button as syntactic sugar, or always force two clicks? Recommend two clicks for safety; revisit after Phase 1C usage.
5. **Active session id source.** How does `ai.js` know the active session id? Verify before writing the widget's `sessionId` plumbing.
6. **Profile mirror cadence.** The client `vehicleProfiles.js` mirrors the seven server fields. If a profile field is added server-side, the mirror drifts silently. Add a server-versioned `KNOWN_PROFILES` hash on `GET /api/vehicle-profiles` so the client can detect drift, or accept the drift risk for now.

## References

- `docs/archive/gcs/2026-05-20-map-widget-codex-review.md` — review that drove this revision (archived).
- `docs/archive/ai-agent/` — archived mission-execution and route-planning PRDs (mission state model, two-approval gates, `VehicleProfile` schema source, vehicle-bound mission templates).
- `docs/cross-cutting/research/flight-controllers/mission-formats.md` — `.plan` format, `vehicleType` semantics.
- `gcs_server/ai/vehicle_profile.py` — `ROVER_DEFAULT`, `QUAD_X500`, `FIXED_WING_DEFAULT`, `KNOWN_PROFILES`, `get_active_profile()`.
- `gcs_server/ai/mission_execution_service.py` — `_build_mission_overlay_payload`, `get_revision_overlay`, `list_revisions`, `approve_revision_for_draft`, `execute_revision`.
- `gcs_server/app.py` — route handlers for mission revisions, mission drafts (approve/reject), mission overlays, mission execute, snapshot, `/ws`.
- `gcs_server/static/replay.html`, `gcs_server/static/replay.js` — current Leaflet usage, future migration target (Phase 2).
- Tracking epic: GitHub [issue #5](https://github.com/vardan6/remote-rover/issues/5).
