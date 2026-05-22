# Map Widget

Authoritative design and implementation brief for the vehicle-aware, reusable map widget that ships first on the AI chat page (`/ai`) and later replaces the monolithic Leaflet code in `replay.html` / `replay.js`. This document records target UX, phase boundaries, and backend contracts. Event wiring and some endpoint shapes remain implementation-plan inputs and are listed in **Open Questions**.

Tracking epic: [issue #5](https://github.com/vardan6/remote-rover/issues/5) (this doc supersedes the issue body where they diverge).

Review history: `docs/archive/gcs/2026-05-20-map-widget-codex-review.md` (review that drove the v2 revision; archived after findings were incorporated into this doc).

---

## Purpose

Operators today approve agent-proposed missions on the AI chat page **without spatial review** — the only existing Leaflet map lives on the replay page as a 3500-line monolith that cannot be reused. Backend mission overlay APIs exist but no frontend renders them. This is a known safety gap; the mission approval and execution boundary now lives in [`../../ai-agent/requirements.md`](../../ai-agent/requirements.md) and [`../../ai-agent/design.md`](../../ai-agent/design.md).

Goal: give the operator spatial review of agent proposals on `/ai` quickly via a small read-only render slice, then grow toward multi-mission management and (eventually) direct-manipulation editing — but only after the backend has the contracts to support those steps safely.


## Current Implementation Reality

Updated 2026-05-21 to reflect Phases 1A–1C shipping.

**Frontend (`gcs_server/static/map/`):**
- `MapWidget.js` — orchestrator; mounts Leaflet map, manages polling, action callbacks, confirm modal, vehicle layer
- `layers/MissionOverlayLayer.js` — renders route polylines and numbered waypoint badges in scene coordinates
- `layers/LiveVehicleLayer.js` — subscribes to `/ws`, draws heading-rotated vehicle arrow marker
- `ui/MissionListPanel.js` — grouped revision list; visibility/focus toggles; approve/reject/execute action buttons; 🔒 badge for executing state
- `data/missionApi.js` — wrappers for all mission overlay, list, approve, reject, execute, and controller-state endpoints
- `data/vehicleProfileApi.js` — vehicle profile wrappers
- `missionListLogic.js` — pure grouping, visibility cap, palette assignment
- `vehicleProfiles.js` — client mirror of the seven-field `VehicleProfile`
- `ai.html` — mounts `MapWidget` on `ai:session-open` and `ai:session-refreshed` events; reads session id via `window.__aiGetActiveSessionId`

**Not yet implemented (Phase 1D/1E):**
- `layers/GeofenceLayer.js`, `layers/TerrainCanvasLayer.js` — Phase 2
- `ui/SelectionPanel.js` — read-only waypoint inspector on marker click
- `ui/KeyboardHelpOverlay.js` — `?` key help
- `state/editState.js` — selection set, dirty waypoints, provenance map
- Backend mutation endpoints for creating/editing/deleting waypoints

**Backend routes that exist (verified):**
- `GET /api/ai/mission-revisions?session_id=...` — list revisions
- `GET /api/ai/mission-revisions/current?session_id=...` — current revision
- `GET /api/ai/mission-revisions/{revision_id}` — single revision
- `GET /api/ai/mission-revisions/{revision_id}/overlay` — overlay payload for a specific revision
- `GET /api/ai/mission-overlays/current?session_id=...` — overlay for the current revision
- `POST /api/ai/mission-drafts/{draft_id}/approve` — **draft approval; also triggers `.plan` export and revision-side sync**. Supports `execute_after_approval=true` body flag.
- `POST /api/ai/mission-drafts/{draft_id}/reject`
- `POST /api/ai/mission-revisions/{revision_id}/execute` — **execution gate**; takes `expected_controller_version` for staleness checks.
- `GET /api/snapshot` and `WS /ws` — telemetry / snapshot / controller events.

**Backend routes that do not exist (verified):**
- `GET /api/vehicle-profile/active`
- `GET /api/vehicle-profiles`
- Any `POST .../mission-revisions` for client-driven revision creation/mutation.
- Any standalone `.plan` export route (export currently happens inside draft approval).
- Any geofence API.

**Mission model facts:**
- Operations are the canonical mission group: `ai_mission_operations` has `id`, `active_revision_id`, `status`.
- `ai_mission_revisions` rows carry `operation_id`, `draft_id`, `status`, and the full `mission` JSON.
- The draft system (`MissionDraftService`) and the revision system (`MissionExecutionService`) coexist; approval drives both in sync.
- Overlay coordinates are **local scene metres** `{x, y, z}` from the mission payload — **not lat/lon**. Mission export projects to WGS84 separately for `.plan` files.
- Per-waypoint provenance is **not in the current payload** — adding it is a backend prerequisite for the editor phase.

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

Phase 1 is split into four shippable slices. Each slice has acceptance criteria and ships independently. Phase 2 is everything that needs new backend contracts.

**Shipped:** Phases 1A, 1B, and 1C are complete as of 2026-05-21. Phase 1D (backend mutation API design) is next.

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

### Phase 1D — Backend mutation API design (no UI yet)

**Goal:** design and add the minimum backend surface that the editor needs. Treated as separate backend work; the widget does not ship editing until this lands.

Required contracts (to be designed, not specified in this doc):
- Create new client-authored revision (operation-scoped or fresh).
- Update waypoint geometry on a revision.
- Insert / delete waypoint on a revision.
- Per-waypoint provenance field added to revision schema and overlay payload (`ai`, `user`, `ai+edited`).
- Stale-edit detection via revision id + version (optimistic concurrency).
- Conflict resolution rules when the agent regenerates over user-edited waypoints (must diff, must not silently overwrite).
- Decision: does "edit an approved revision" create a new `proposed` successor under the same operation, or supersede in place? Default recommendation: new successor; preserves history and the two-approval model.

Out of scope for 1D itself:
- The UI consuming these contracts (that's Phase 1E).
- Settings UI; geofence.

### Phase 1E — Direct manipulation editor

Built only after 1D lands. UX target — already designed at length in v1 of this doc — preserved verbatim below in **Editing Model (Deferred)** so the spec does not lose information. Acceptance criteria for 1E will be drafted when 1D contracts are concrete.

### Phase 2 — Out of scope here

- Replay page migration (extract `TerrainCanvasLayer` and historical-track layer from `replay.js`; rebuild replay on `MapWidget`).
- Elevation profile panel — **required before the first multirotor mission ships**.
- Floating / pop-out / second-monitor window modes (design hook only — `MapWidget` must support re-parenting via `invalidateSize()`).
- 3D map view.
- Snap-to-road, edit-during-execution.
- Bulk-edit action bar for multi-selected waypoints.
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
- Touch / mobile: list panel + read-only map + buttons MUST be usable. Drag editing (Phase 1E) MAY degrade to read-only on touch.

## Empty / Error / Offline States

- **No mission overlay available:** center on `(0, 0)` in scene mode, list shows a single CTA card *"No missions yet. Ask the agent."* (`➕ New mission` appears only when Phase 1E ships.)
- **Overlay API failure:** non-blocking banner at top of map area: *"Mission overlay unavailable — retrying in 5 s."* Manual refresh button. Map still pans/zooms.
- **Vehicle telemetry failure / no `/ws`:** live vehicle marker hides. Mission overlay rendering is unaffected.
- **Active-profile API missing:** widget uses `rover_default` and logs a console warning. No blocking dialog.

## Editing Model (Deferred — Phase 1E target)

Recorded here so the design intent is not lost. Implemented only after Phase 1D contracts land.

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

Phase 1D and 1E acceptance criteria are deferred and will be added when 1D contracts are concrete.

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
