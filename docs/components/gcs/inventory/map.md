# Map widget inventory — `map/` (MapWidget module)

Pass A extraction (mechanical). Source: the ES-module map widget promoted to
top-level `map/` (~7,200 lines, 35 files), per ADR 0037. Entry `map/index.js` →
`MapWidget.js` (2,496 lines, builds the DOM + orchestrates), UI panels in
`map/ui/`, on-map render split by source into `map/sources/world/` and
`map/sources/authored/`, shared state in `map/state/`. Styles in
`frontend-vanilla/style.css`. The widget is mounted on `ai.html` and
`mission-console.html` (see [`ai.md`](ai.md),
[`mission-console.md`](mission-console.md)); it is **not** page-specific.

**This whole module is already Embedded in the new app.** `frontend/src/widgets/
MapWidgetPanel.tsx` dynamic-imports `../../../map/index.js` and
does `new MapWidget(host); widget.mount()` inside a dockview panel — the legacy
vanilla widget runs verbatim. So the *implementation* gap is near-zero; the gap
is **wiring + parity-of-intent**, not re-coding. Three caveats from the embed:

1. It is mounted with **no opts** (`new MapWidget(host)`): no `sessionId`, no
   `statusBar`, no `missionListPosition`. ⇒ the session pill reads "No session",
   every `_pushStatus()` is a silent no-op (no StatusBar sink), and the list
   defaults to the **left** (mission-console mounts it `right`). Mission overlays
   that need a session (`getCurrentOverlay`) won't load; CRUD/overlay-by-id still
   works.
2. It self-mounts its **own** layer/view/fit/authoring controls (operator-console.md:78
   "self-contained: includes its own layer/object/visibility controls"), so the
   new design does **not** re-chrome it — those rows are Embed-by-cascade, not Rebuild.
3. It opens its **own** `/ws` sockets for the live-vehicle + basemap-GPS markers,
   independent of the React data layer.

`planned?` / `implemented?` pre-filled; `target` + `decision` are blank — filled
in **Pass B (INV-B)**.

**Pre-fill key.** `planned?`: operator-console.md names **Map** as a shipped
singleton-ish widget — "the existing vanilla `MapWidget` is hosted inside a
dockview panel via `dockview-core`" (line 52) and "Map | design for many, ship
one | self-contained: includes its own layer/object/visibility controls;
per-instance view state" (line 78); Replay/Map-track split is line 84. So the
whole tree reads **yes (Embed — operator-console.md:52,78)** and a node decision
of Embed will cascade. `implemented?`: searched `frontend/src/` — the only map
file is `MapWidgetPanel.tsx`, a thin embed host (no React re-implementation of
any sub-widget); `rg leaflet|MapWidget|mission` finds only the embed + CSS. So
every row is **yes (embedded as-is)**, qualified by the three caveats above where
they bite (session pill, status sink, list side).

**Pass B summary — whole tree is Embed by cascade.** The `map` node gets **Embed**
and every child inherits unless a specific wiring gap or intent difference warrants
an override. Overrides noted per row. The three wiring gaps to close in a parity
slice: (1) pass `sessionId`, (2) pass a `statusBar` sink, (3) pass
`missionListPosition:'right'` in Mission Console context. Cross-widget focus
coupling (CTA → `#ai-message-input`, keyboard `/`) needs a dock-native event
instead of DOM id targeting.

## 1. Decision table

### Embed host & layout shell (`MapWidget._buildDOM`)

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `map` | node | panel | — | Root widget built into a host `div` by `MapWidget.mount()`; `crs:L.CRS.Simple` Leaflet map (zoom −6..8, snap .25). Self-contained: list + map + own controls + overlays | yes (Embed — operator-console.md:52,78) | yes (embedded via MapWidgetPanel.tsx) | `MapWidgetPanel.tsx` | Embed | Node decision cascades to all children |
| `map.head` | node | panel | "Mission Map" + session pill | `div.map-widget-head`: `<h2>` title + `span.pill.warn.map-widget-session-pill` showing `sessionId \|\| 'No session'` | yes | partial: pill always "No session" (mounted without sessionId) | `MapWidgetPanel.tsx` | Embed | Wire: pass `sessionId` from the active AI session or replay selection so pill reads correctly |
| `map.shell` | node | panel | — | `div.map-widget-shell`; gets `.mission-list-right` when `opts.missionListPosition==='right'`; sets `--map-list-width` | yes | partial: embed omits `missionListPosition` → always left | `MapWidgetPanel.tsx` | Embed | Wire: pass `missionListPosition:'right'` when in Mission Console context |
| `map.list` | node | panel | — | `div.map-widget-list` host for `MissionListPanel` (see `map.list.*`) | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list-resizer` | leaf | separator | "Resize mission list" | `button.map-list-resizer[role=separator]`; pointer-drag + arrow keys set list width 180–480px; persists `gcs-map-list-width` in localStorage | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.col` | node | panel | — | `div.map-widget-map-col` stacks layer bar + map wrap | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.wrap` | node | panel | — | `div.map-widget-wrap` positioned container for map canvas + all floating overlays (empty/edit/selection/marquee/ctrl-right/info/toolbar/basemap/constraints/hint/confirm) | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.canvas` | leaf | panel | — | `div.map-widget-map`; Leaflet map element; `missionPane` z=470; ResizeObserver → `invalidateSize`; classes `is-edit-mode`/`is-locked` toggle during edit | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.empty` | node | panel | "No missions yet" / "Ask the agent in chat to plan a mission." / "Go to chat" | `div.map-widget-empty[aria-live]`; CTA scrolls `.ai-chat-panel` + focuses `#ai-message-input`; hidden when scene loaded or overlays present | yes | partial: CTA targets AI-page DOM ids not present in dock | `MapWidgetPanel.tsx` | Redesign | Replace DOM-id CTA with a cross-widget event (e.g. `CustomEvent('gcs:focus-ai-chat')`); text can stay |

### Mission list panel (`ui/MissionListPanel.js`)

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `map.list.panel` | node | panel | — | `div.mission-list-panel` = header + batch-bar + rows; full innerHTML rebuild per `renderMissions`, preserves scrollTop | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.header` | node | panel | "Missions" | `div.mission-list-header`: title + optional sort-label + action icons | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.header.sort-label` | leaf | label | "⇅ {label}" | shown only when sort ≠ `updated_desc` | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.header.new` | leaf | button(icon +) | "New mission" | `[data-new-mission]` → `createMission({name:'New mission'})` → refresh → assign colour → enter edit | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.header.settings` | leaf | link(icon gear) | "Mission lifecycle settings" | `<a href="/settings?tab=mission-lifecycle">` | unsure (links to legacy Settings page; see `settings.md`) | yes (embedded, but href is legacy route) | `MapWidgetPanel.tsx` | Redesign | Update href to dock Settings panel / Settings category deep-link once Settings widget lands |
| `map.list.header.overflow` | leaf | button(icon ⋯) | "Mission list options" | `[data-overflow-menu]` → opens `MissionListOverflowMenu` (sort + import/export) | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.batch` | node | panel | — | `div.mission-batch-bar[role=toolbar]`: select-all + count + contextual verbs + show/hide-all | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.batch.select-all` | leaf | checkbox | "Select all" / "Deselect all" | `[data-batch-toggle-select-all]`; `indeterminate` when partial; toggles whole Selected set | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.batch.count` | leaf | label | "N selected" / "None selected" | `span.mission-batch-count[aria-live]` | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.batch.context-verbs` | node | panel | — | `span.mission-batch-actions`; **focus-first** acting target → contextual verbs (Edit/Execute/Pause/Resume/Stop/Done) for one mission, or Delete+Clear for multi-select | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.batch.verb.edit` | leaf | button(icon) | "Edit waypoints" | `[data-edit-mission-id]`; shown for editable status (proposed/planning/exported/cutover_pending) & not active → `_onEditRequested` | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.batch.verb.execute` | leaf | button(icon ▶) | "Upload plan to controller" / "Resume" | `[data-execute-mission-id]`/`[data-resume-mission-id]`; legacy direct upload (not BT execution) → confirm modal → `executeMission` | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | Note: legacy direct upload path, not BT execution (ADR 0023); flag for mission planner phase |
| `map.list.batch.verb.pause` | leaf | button(icon ⏸) | "Pause mission" | `[data-pause-mission-id]` → `pauseMission` | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.batch.verb.stop` | leaf | button(icon ⏹) | "Stop mission" | `[data-stop-mission-id]` → `stopMission`; shown while running/paused | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.batch.verb.done` | leaf | button(icon ✓) | "Finish editing" | `[data-done-edit-mission-id]` → clear edit + refresh | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.batch.delete-selected` | leaf | button(icon trash) | "Delete selected missions" | `[data-delete-selected]` (multi-select only) → bulk delete w/ confirm + guards | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.batch.clear` | leaf | button(icon ✕) | "Clear selection" | `[data-clear-selection]` | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.batch.show-hide-all` | leaf | button(icon eye) | "Show/Hide all missions" | `[data-batch-action]`; toggles all overlay visibility; executing missions stay visible; disabled when nothing hideable | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.rows` | node | listbox | — | `div.mission-list-rows`; one `map.list.row` per Mission (ADR 0021 §2: one row=one Mission); sorted via `missionSortPreference` | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.empty` | node | panel | "No missions yet" / "Ask the agent in the chat above…" / "↑ Go to chat" | shown when no missions | yes | partial: CTA targets AI-page DOM ids | `MapWidgetPanel.tsx` | Redesign | Same CTA coupling issue as `map.empty`; replace with cross-widget event |
| `map.list.row` | node | panel | — | `div.mission-list-row` + status class (`is-proposed/approved/executing/completed/superseded`) + `is-focused/selected/editing`; full-row click focuses, shift/ctrl-click selects | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.row.color-chip` | leaf | button | "Change mission colour" | `[data-color-chip-mission-id]`; `--mission-color`; opens `MissionColorPicker` | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.row.select` | leaf | checkbox | "Select mission {name}" | `[data-select-mission-id]`; click carries shiftKey for range; preventDefault keeps it synced to authoritative set | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.row.focus` | leaf | button | (mission body) | `[data-focus-mission-id][aria-pressed]`; vehicle icon + origin badge + title + meta (index · pts · status · date) | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.row.title` | leaf | label/input | mission name | `[data-rename-mission-id]`; **double-click → inline rename input** (Enter/blur commit, Esc cancel) → `renameMission` | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.row.stop` | leaf | button(⏹) | "Stop mission" | trailing inline Stop, only on running/paused rows (urgent action carve-out) | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.row.menu` | leaf | button(⋯) | "More actions" | `[data-row-menu-mission-id]` → `MissionRowMenu` (Edit/Rename/Delete) | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.list.row.eye` | leaf | button(icon eye) | "Show/Hide mission overlay" | `[data-toggle-mission-id]`; locked+disabled while executing | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |

### Mission list popovers

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `map.color-picker` | node | dialog | "Choose mission colour" | `div.mission-color-picker[role=dialog]`; anchored popover; swatch grid + custom hex + reset; hover/focus fires live `onPreview` | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.color-picker.swatch` | leaf | button | (palette colour) | `MISSION_COLOR_PALETTE`; click → `onPick` → persist via `setMissionColor` | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.color-picker.custom` | leaf | input(color) | "Custom…" | native `<input type=color>`; input=preview, change=pick | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.color-picker.reset` | leaf | button | "↺ Reset" | clears override → palette default → `setMissionColor(id,'')` | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.overflow-menu` | node | dialog | "Mission list options" | `div.mission-list-overflow-menu[role=dialog]`; sort radio group + File group | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.overflow-menu.sort` | leaf | radio-group | "Sort by" | `SORT_OPTIONS` radios → `missionSortPreference.set` → re-render | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.overflow-menu.export` | leaf | button | "Export missions…" | downloads `missions-YYYY-MM-DD.json` (name/origin/waypoints per mission) | unsure (no export named in operator-console.md) | yes (embedded) | `MapWidgetPanel.tsx` | Embed | Keep as-is; export/import are useful even if not in the design spec |
| `map.overflow-menu.import` | leaf | button | "Import missions…" | file picker → `createMission` per item → refresh | unsure | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.row-menu` | node | menu | "Mission actions" | `div.mission-row-menu[role=menu]`: Edit waypoints (status-gated) / Rename / Delete (guard-gated) | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |

### On-map render layers (`map/sources/world/`, `map/sources/authored/`)

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `map.layer.terrain` | leaf | canvas | — | `TerrainCanvasLayer` from `fetchSceneMap()`; toggled by Terrain checkbox / view mode | yes (Embed) | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.layer.scene-objects` | leaf | canvas | — | `SceneObjectsLayer` (roads + objects); independent road/object visibility | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.layer.grid` | leaf | canvas | — | `GridLayer`; metric grid; Grid checkbox | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.layer.mission-overlay` | node | vector | — | `MissionOverlayLayer.renderMany`; per-mission route lines + waypoint markers, palette colour, focus opacity 1 vs 0.25; editable layer for the mission being edited | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.layer.geofence` | leaf | vector | — | `renderGeofence(payload.geofence, origin)` on scene views | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.layer.scene-constraints` | leaf | vector | — | `_renderSceneConstraints` plots planning constraints (allowed corridor green / blockage orange, hard solid / soft dashed) on scene views via origin transform | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.layer.scene-sketch` | leaf | vector | — | `_refreshSceneSketch` mirrors the in-progress WGS84 sketch onto scene views | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.layer.live-vehicle` | leaf | marker | — | `LiveVehicleLayer` — own `/ws` socket; heading-rotated `.map-vehicle-marker` at scene-metre `position.x/y` | yes | yes (embedded; own WS) | `MapWidgetPanel.tsx` | Embed | |

### Top-right controls column (`map.ctrl-right`)

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `map.ctrl-right` | node | panel | — | `div.map-ctrl-right`; view-mode card + fit card (layer bar lives separately above map) | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.view-mode` | leaf | select | "View" | `select.map-view-mode-select`: Virtual Terrain / CAD / Heightmap / Basemap → `_applyViewMode` (presets layer combo; Basemap swaps to OSM panel) | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.nav-mode` | leaf | select(disabled) | "Nav" — "Free Pan" | `select.map-nav-mode-select` disabled (fixed free-pan) | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.layer-bar` | node | panel | "Map layers" | `div.map-layer-bar`: 4 checkboxes Terrain/Roads/Objects/Grid → `_onLayerToggle`; synced by view-mode preset | yes (Embed; "own layer controls" operator-console.md:78) | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.fit` | node | panel | "Fit view" | `div.map-fit-toolbar`; 3 icon buttons | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.fit.terrain` | leaf | button(icon) | "Fit Terrain" | fit scene bounds; disabled w/o scene | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.fit.mission` | leaf | button(icon) | "Fit Mission" | fit focused mission route; disabled w/o focused payload | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.fit.all` | leaf | button(icon) | "Fit All" | fit union of all visible missions + scene | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |

### Authoring toolbar (`ui/MapAuthoringToolbar.js`)

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `map.authoring` | node | panel | "Map authoring tools" | `div.map-authoring-toolbar` docked bottom; 3 swap states: launcher / idle / active-tool; Escape cancels tool → collapses | yes (Embed) | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.authoring.launcher` | leaf | button | "✏ Authoring" (+ draft dot) | collapsed state; draft dot when sketch in progress | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.authoring.add-waypoint` | leaf | button | "Add waypoint" | idle tool → `editState.setEditMode('add')`; enabled only w/ editable revision | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.authoring.corridor` | leaf | button | "Corridor pattern" | starts corridor sketch (basemap or scene via origin); Spacing/Passes/Altitude fields; live footprint preview | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.authoring.survey` | leaf | button | "Survey area" | starts survey rect sketch; 2 corners + drag-to-rotate handle; lawnmower route preview | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.authoring.geofence` | leaf | button | "Mission geofence" | starts inclusion-fence polygon sketch (≥3) → `setMissionGeofence` on focused mission | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.authoring.constraints-menu` | leaf | button | "Constraints ▾" | opens `ConstraintsPanel` (ADR 0025 planning constraints) | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.authoring.active.fields` | node | panel | "Spacing / Passes / Altitude" | number inputs; input fires live param preview; Passes corridor-only | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.authoring.active.undo` | leaf | button | "↩ Undo" | remove last sketch vertex | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.authoring.active.finish` | leaf | button | "Generate corridor/survey" / "Save geofence/constraint" | commit; enabled by vertex-count rule per tool | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.authoring.active.cancel` | leaf | button | "Cancel sketch" | discard draft only (never deletes persisted objects) | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.authoring.active.done` | leaf | button | "Done" | leave add-waypoint mode | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |

### Basemap (OSM) view (`ui/BasemapPanel.js`)

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `map.basemap` | node | panel | — | `div.map-basemap-panel` (`inset:0; z:450`); own `L.map` w/ OSM tiles (EPSG:3857); shown when view mode = Basemap; read-only WGS84 plot of focused mission (ADR 0022) | yes (Embed) | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.basemap.tiles` | leaf | tile-layer | — | OpenStreetMap tiles + attribution | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.basemap.mission` | leaf | vector | — | `render(payload)` plots route line + waypoint markers + stored geofence + rally points by lat/lon; auto-fits | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.basemap.gps-vehicle` | leaf | marker | — | own `/ws` socket; live heading-rotated GPS marker from telemetry `gps.lat/lon` | yes | yes (embedded; own WS) | `MapWidgetPanel.tsx` | Embed | |
| `map.basemap.sketch` | leaf | vector | — | draws corridor/survey/fence/constraint sketch; draggable vertex handles + 15px vertex snapping + survey rotate handle | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.basemap.constraints` | leaf | vector | — | `renderConstraints(list)` plots persisted constraints (own layer) | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |

### Constraints list panel (`ui/ConstraintsPanel.js`, ADR 0025)

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `map.constraints` | node | dialog | "Planning constraints" | `div.map-constraints-panel[role=dialog]`; note "Planning only — hard rules reject violating routes…"; row per constraint | yes (Embed) | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.constraints.row` | node | panel | "{name} · {kind} · {hard/soft}" | swatch (green allowed / orange blockage; dashed if soft); muted when disabled | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.constraints.row.rename` | leaf | button | "Rename" | `window.prompt` → `updateConstraint{name}` | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.constraints.row.rule` | leaf | button | "Make hard"/"Make soft" | toggle rule → `updateConstraint{rule}` | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.constraints.row.enable` | leaf | button | "Enable"/"Disable" | reversible toggle → `updateConstraint{enabled}` | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.constraints.row.edit-shape` | leaf | button | "Edit shape" | re-open polygon sketch on map (≥3 verts) | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.constraints.row.delete` | leaf | button | "Delete" | confirm → `deleteConstraint` | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |

### Edit-mode chrome & overlays

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `map.edit-banner` | node | panel | "Editing — {status} · rev …{id}{mode}" + "✕ Exit edit" | `div.map-edit-banner`; shown during edit; exit clears edit + refresh | yes (Embed) | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.selection-panel` | node | panel | "Waypoint N" + X/Y/Z/Provenance | `SelectionPanel` floating inspector; shown when exactly 1 waypoint selected | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.bulk-bar` | node | panel | "N selected · Alt: __ Apply · Delete N · ✕" | `BulkEditActionBar`; shown when ≥2 waypoints selected; set-altitude + bulk delete | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.marquee` | leaf | panel | — | `div.map-marquee` rubber-band rectangle for multi-select on empty map | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.info-bar` | node | panel | "x __ m  y __ m · ground z · GPS · WP sel" | `div.map-info-bar--map`; live cursor scene coords, ground sample, WGS84 (when origin), selected-WP detail | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.hint-toast` | leaf | panel | (transient hints) | `HintToasts` e.g. "Hold Alt to snap to a waypoint" | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.context-menu` | node | menu | "Insert before/after · Delete · Move to vehicle" | `ContextMenu` on waypoint right-click | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.confirm-modal` | node | dialog | "Upload linear plan to controller?" | `div.map-confirm-modal[role=dialog]`; legacy direct upload warning + rev/controller-version + Cancel/Upload | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | Legacy direct upload path (ADR 0023 note); keep for now |
| `map.confirm-banner` | node | alert | "Armed: {mission} — confirm to start" + countdown + "▶ Play" + "✕" | `ConfirmExecutionBanner` (ADR 0021 §1); polls execution state; bounded confirm window; needs `sessionId` | yes | partial: needs sessionId — inert in unwired embed | `MapWidgetPanel.tsx` | Embed | Wire: pass `sessionId` to activate confirm banner (wiring gap #1) |
| `map.keyboard-help` | node | dialog | "Map keyboard shortcuts" | `KeyboardHelpOverlay` `<dialog>`; 12-row shortcut table; opened with `?` | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.elevation` | node | panel | "Elevation Profile" + clearance chip + collapse | `ElevationProfilePanel`; SVG terrain/route/clearance chart; dots clickable → select WP; CLEAR/LOW/BELOW chip | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |

### Status bar (`ui/StatusBar.js`)

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `map.status-bar` | node | panel | "Status" + count + collapsible log | `StatusBar` mounted by the **page** (not MapWidget) and passed as `opts.statusBar`; `_pushStatus` routes here | unsure (GCS status surface; see `ai.md` `ai.status-bar`) | **no** in embed: mounted without `statusBar` → all pushes are no-ops | `MapWidgetPanel.tsx` | Redesign | Pass a `statusBar` sink that routes to workspace toast/notification surface (wiring gap #2) |

### Cross-cutting behaviors

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `map.behavior.keyboard` | node | (behavior) | — | shell-scoped keymap: `?` help, `/` focus session search (AI-page id), Esc cascade, V/A modes, [ ] step, Del delete, F focus | yes | partial: `/` targets `#ai-session-search` absent in dock | `MapWidgetPanel.tsx` | Redesign | Drop the `/` shortcut (no global search target in dock); other keys work as-is via embed |
| `map.behavior.polling` | leaf | (behavior) | — | 5s poll: refresh missions (paused mid-edit / picker-open) + execution-state always | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.behavior.smart-binding` | leaf | (behavior) | — | new mission auto-promoted Active+Visible; executing always visible; Active⊆Visible invariant (ADR 0021 §4) | yes | yes (embedded) | `MapWidgetPanel.tsx` | Embed | |
| `map.behavior.session-binding` | node | (behavior) | — | `setSessionId` resets overlay/selection/focus + execution state; page re-binds on `ai:session-open/refreshed` | yes | partial: embed never sets a session id | `MapWidgetPanel.tsx` | Rebuild | Wire `sessionId` from React store into MapWidget opts on mount/update (wiring gap #1 root) |
| `map.behavior.stale-recovery` | leaf | (behavior) | — | execute failures (`stale_revision` / `stale_controller_version`) → refresh + re-pin + status message | yes | partial: status messages go to a null StatusBar | `MapWidgetPanel.tsx` | Embed | Status messages begin working once `statusBar` sink is wired (gap #2) |

## 2. Style appendix (lossless backstop)

Values keyed by `id`; `@ style.css:<line>` is authoritative. Node rows carry
layout; leaf rows carry appearance.

### Layout (nodes)

- `map.ctrl-right` — `.map-ctrl-right` `@ style.css:853`; children `@866`.
- `map.authoring` (dock) — `.map-authoring-toolbar-dock` `@871`; `.map-authoring-toolbar` `@882`; sections `.mat-section` `@947`; launcher btn `@955`; responsive `@1314,1337`.
- `map.shell` — `.map-widget-shell` `@4363`; `.mission-list-right` reorders cols `@4372,4376,4381,4386`; resizing `@4452`.
- `map.head` — `.map-widget-head` `@4426`; `h2` `@4436`.
- `map.list-resizer` — `.map-list-resizer` `@4457`; hover/focus/resizing `@4478`.
- `map.list` — `.map-widget-list` `@4492`.
- `map.col` — `.map-widget-map-col` `@5292`.
- `map.canvas` — `.map-widget-map` `@5341`; leaflet zoom ctl `@1502`.
- `map.list.panel` — `.mission-list-panel` `@4503`; `.mission-list-rows` `@4520`; header `@4530`.
- `map.list.batch` — `.mission-batch-bar` `@4897`; select `@4909`; count `@4925`; actions `@4945`; visibility `@4937`.
- `map.list.row` — `.mission-list-row` `@4848`; `is-selected` `@4889`; `is-focused` `@5209`; status stripes `@5186,5190`; leading `@5226`; main `@5236`.
- `map.color-picker` — `.mission-color-picker` `@4614`; grid `@4626`; custom `@4664`.
- `map.overflow-menu` — `.mission-list-overflow-menu` `@4711`; groups `@4722`; sort list `@4742`.
- `map.row-menu` — `.mission-row-menu` `@5099`.
- `map.constraints` — `.map-constraints-panel` `@1047`.
- `map.elevation` — `.map-elevation-panel` `@6875`; header `@6882`; chart wrap `@6915`.
- `map.edit-banner` — `.map-edit-banner` `@6467`.
- `map.confirm-banner` — `.map-confirm-banner` `@6510`; urgent `@6528`.
- `map.confirm-modal` — `.map-confirm-modal` `@5485`; dialog `@5500`.
- `map.selection-panel` — `.map-selection-panel-wrap` `@6652`; panel `@6662`; details `@6694`.
- `map.context-menu` — `.map-context-menu` `@6716`.
- `map.keyboard-help` — `.map-keyboard-help-dialog` `@6748`; table `@6770`.
- `map.info-bar` — `.map-info-bar--map` `@1402`; spans `@1416,1428`.
- `map.fit` — `.map-fit-actions` `@1274`; `.map-overlay-card` `@1208`.
- `map.bulk-bar` — `.map-bulk-bar` (see `rg map-bulk-bar`).

### Appearance (leaves)

- `map.head` pill — `.map-widget-session-pill` inherits `.pill.warn` (token set in `ai.md`).
- `map.list.row.color-chip` — `.mission-row-status` `@4859`; hover `@4869`.
- `map.list.row.select` — `.mission-row-select` `@4873`; box `@4882`.
- `map.list.row.focus` — `.mission-row-focus` `@5195`; vehicle/origin `@5218,5231`; title/meta `@5242,5249,5254`.
- `map.list.row.eye` — `.mission-row-eye` `@5276`; locked `@5478`.
- `map.list.row.menu` — `.mission-row-menu-btn` `@5072`; menu items `@5113`; danger `@5134`.
- `map.list.row.stop` — `.mission-row-action-btn.is-stop` `@5446`.
- `map.list.batch.verb.*` — `.mission-context-icon-btn` `@5012`; execute/pause `@5033`; done `@5044`; stop/delete `@5049`.
- `map.list.batch.show-hide-all` — `.mission-batch-icon-btn` `@5147`; svg `@5162`.
- `map.list.header.{new,settings,overflow}` — `.mission-list-header-icon-btn` `@4570`; has-active-sort `@4595,4600`.
- `map.list.header.sort-label` — `.mission-list-sort-label` `@4553`.
- `map.color-picker.swatch` — `.mission-color-swatch` `@4633`; hover `@4647`; current `@4657`; reset `@4692`.
- `map.overflow-menu.sort` — `.mission-overflow-sort-row` `@4748`; radio `@4773`.
- `map.fit.*` — `.map-tool-button` `@1282`/`.map-fit-btn` `@1168`; hover `@1298`; disabled `@1303`.
- `map.view-mode`/`map.nav-mode` — `.map-view-mode-select`/`.map-nav-mode-select` focus `@1190`.
- `map.authoring.*` buttons — `.map-authoring-toolbar button` `@922`; hover `@930`; active `@935`; disabled `@940`; inputs `@901,907`.
- `map.basemap.sketch` handles — `.map-vertex-handle(-icon)` `@1029,1032,1041`; `map.basemap` survey handle `.map-survey-handle(-icon)` `@1012,1015,1024`.
- `map.layer.live-vehicle` / `map.basemap.gps-vehicle` — `.map-vehicle-marker` `@5569`; `::before` `@5579`.
- `map.elevation` chip — `.map-elev-chip` `@6901`; ok/warn/danger `@6911,6912,6913`; toggle `@6897`; empty `@6915`.
- `map.edit-banner` text/exit — `.map-edit-banner-text` `@6485`; `.map-edit-exit-btn` `@6493`.
- `map.confirm-banner` parts — text `@6533`; countdown `@6540`; play `@6547`; dismiss `@6562`.
- `map.confirm-modal` parts — title `@5510`; body `@5516`; actions `@5531`; cancel `@5537`; ok `@5552`.
- `map.selection-panel` parts — header `@6672`; title `@6679`; close `@6684`; dt/dd `@6701,6705`.
- `map.context-menu.item` — `.map-context-menu-item` `@6730`; hover `@6743`.
- `map.keyboard-help` parts — title `@6764`; key `@6785`; footer/close `@6795,6800`.
- `map.empty` / `map.list.empty` — `.map-empty-*` `@5365,5370,5375`; `.mission-list-empty*` `@4782,4799,4804,4809`.
- `map.marquee` — `.map-marquee` `@6843`.
- `map.hint-toast` — `.map-hint-toast` `@6855`.
- `map.status-bar` — `.gcs-status-bar` `@4189`; toggle `@4196`; count `@4223`; log `@4242`; rows `@4261`; warn/error `@4289,4293`.

### Dead/legacy CSS observed

`.mission-row-action-btn.is-approve` (@5410) / `.is-reject` (@5419) are styled but
**not rendered** — approve/reject were removed (play gates execution, ADR 0021 §4);
verify nothing else emits them before dropping.

### Theme tokens (resolve in `style.css` `:root`/`[data-theme]`)

`--accent`, `--accent-soft`, `--line`, `--muted`, `--text`, `--panel`,
`--panel-strong`, `--bg-base`, `--mission-color` (per-row), `--map-list-width`
(runtime). Pill/chat tokens are listed in `ai.md`.
