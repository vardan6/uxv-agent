# Replay page inventory — `static/replay.html` + `static/replay.js`

Pass A extraction (mechanical). Source: `backend/static/replay.html`
(237 lines), `backend/static/replay.js` (1,572 lines), styles in
`backend/static/style.css`. Target app: `frontend/` — no replay widget exists
yet; present widgets are `AIChatWidget.tsx`, `MapWidgetPanel.tsx`, `ClockWidget`,
`DriveControlsWidget`, `NotesWidget`, `TelemetryWidget`, `VideoWidget`.

**This page is a standalone replay workstation, not a re-mount.** Unlike
mission-console (which re-mounts the AI chat shell + `MapWidget`), `replay.js`
builds its **own** Leaflet map directly (`#replay-map`, scene/geo dual mode), its
own scene renderer (terrain canvas, roads, objects, grid, compass, telemetry
points), and a transport (play/pause/seek/speed/scrubber). It shares only the
**session sidebar** vocabulary with `mission-console.js` — but here the sidebar is
**richer** (sort popover, delete button) **and live**: selecting a session loads
it and drives the map (the inert-selection gap flagged in `mission-console.md`
does **not** apply here). The map here is a *replay-specific reimplementation*,
**not** the embeddable `static/map/` `MapWidget` inventoried in `map.md`.

`planned?` / `implemented?` pre-filled. Pass B decisions filled below.

**Pre-fill key.** `planned?`: the new design doc
([operator-console.md](../design/operator-console.md)) widget table lists
**Replay Sessions** (line 84, "singleton; per-map track visibility is a Map
toggle") and **Replay Playback Controls** (line 85, singleton) as planned
widgets, and the data layer names `/api/replay/*` over TanStack Query (line 27).
So sidebar + transport rows read **yes (planned widget,
operator-console.md §widget-table)**. The replay **map/scene** itself is not a
separately named widget — the design intends per-map track visibility to ride the
**Map** widget's layer toggles (line 84), so replay-map rows read
**unsure (folds into Map widget? operator-console.md:84)** pending Pass B.
`implemented?`: searched `frontend/src/` for `replay`/`/api/replay`/`scrubber`/
`playback`/`scene-map`/`rollover` — the **only** hit is a comment in
`frontend/src/data/runtimeStore.ts:12` ("Persistent/queryable data (replay, AI
sessions, missions) is the Domain Stores"); no replay widget, store, hook, map, or
transport exists. So every row is **no**.

**Pass B node cascade rule:** node decision applies to all child leaves below it
unless a leaf row carries an override note.

## 1. Decision table

### Page shell & layout

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `rp` | node | panel | — | Page root `main.app-shell[data-page="replay"]` → `section.replay-shell`. Stacks: `replay-split-pane` (sidebar ∣ divider ∣ map+controls) → height-divider → `replay-bottom-grid` (telemetry + records). `initReplay()` boots: shell → resizers → actions → load scene-map → ensureMap → load sessions → auto-load preferred session | yes (Replay flagship, roadmap:151 "Replay widgets") | no | — | Drop | dockview workspace replaces fixed page shell; child panels dock as widgets |
| `rp.intro` | leaf | panel | — | `<section data-page-intro>`; `GCSCommon.initShell` injects title "Recorded Sessions" + subtitle | no | no | — | Drop | page-intro pattern is old-app nav; not used in dockview |
| `rp.split-pane` | node | panel | — | `#replay-split-pane.replay-split-pane`; CSS grid `sidebar∣divider∣map` + `controls`; desktop (≥1101px) honors `--replay-sidebar-width`/`--replay-pane-height` from localStorage | yes (parity) | no | — | Drop | dockview handles split/sizing |
| `rp.split-divider` | leaf | separator | "Resize sessions and map panels" | `#replay-split-divider[role=separator][tabindex=0]`; pointer-drag sets sidebar width 260px–42% of pane (`gcs-replay-sidebar-width`) | no | no | — | Drop | dockview-native |
| `rp.height-divider` | leaf | separator | "Resize replay area height" | `#replay-height-divider[role=separator][tabindex=0]`; pointer-drag sets pane height 560–1600px (`gcs-replay-pane-height`); dblclick → auto height | no | no | — | Drop | dockview-native |

### Sessions sidebar (`rp.side`)

Node decision: **Rebuild / `ReplaySessionsWidget.tsx`**. All leaves cascade Rebuild unless noted.

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `rp.side` | node | panel | "Sessions" / "Replays" | `article.panel.replay-sidebar`; head + toolbar + list. **Live browser** — selecting a session loads it and drives the map (contrast `mission-console.md` `mc.replay`, which is inert) | yes (Replay Sessions, operator-console.md:84) | no | ReplaySessionsWidget.tsx | Rebuild | |
| `rp.side.head.kicker` | leaf | label | "Sessions" | static `.section-kicker` | no | no | ReplaySessionsWidget.tsx | Rebuild | |
| `rp.side.head.title` | leaf | label | "Replays" | static `<h2>` | no | no | ReplaySessionsWidget.tsx | Rebuild | |
| `rp.side.head.count` | leaf | pill | "N session(s)" | `#session-count-pill`; `renderSessions()` → `sessions.length` (singular/plural) | yes (parity) | no | ReplaySessionsWidget.tsx | Rebuild | |
| `rp.side.head.current` | leaf | pill | "No active session" / session id | `#current-session-pill`; shows `loadedSession.session_id ?? currentSessionId ?? "No session selected"` | yes (parity) | no | ReplaySessionsWidget.tsx | Rebuild | |
| `rp.side.toolbar` | node | panel | "Session actions" | `div.session-toolbar[role=toolbar]` | yes (parity) | no | ReplaySessionsWidget.tsx | Rebuild | |
| `rp.side.toolbar.refresh` | leaf | button(icon) | refresh — "Refresh sessions" | `#refresh-sessions`; `loadSessions()` → `GET /api/replay/sessions` → `{sessions, current_session_id}` | yes (parity) | no | ReplaySessionsWidget.tsx | Rebuild | |
| `rp.side.toolbar.rollover` | leaf | button(icon "+") | plus — "Start new session" | `#rollover-session`; `rolloverSession()` → `POST /api/replay/sessions/rollover {reason:"replay_ui_rollover"}` then reload | yes (parity) | no | ReplaySessionsWidget.tsx | Rebuild | |
| `rp.side.toolbar.sort` | node | panel | "Sort sessions" | `.session-sort-control`; trigger + popover; outside-click + Esc close | yes (parity) | no | ReplaySessionsWidget.tsx | Rebuild | richer than mission-console (which has no sort) |
| `rp.side.toolbar.sort.trigger` | leaf | button(icon) | sort glyph + "Sort: <field>" | `#session-sort-trigger[aria-haspopup=dialog]`; toggles `#session-sort-popover`; summary `#session-sort-summary` reflects field+order | yes (parity) | no | ReplaySessionsWidget.tsx | Rebuild | |
| `rp.side.toolbar.sort.field` | leaf | button×4 | "Date" / "Telemetry frames" / "Controls" / "Events" | `[data-session-sort-field=started_at\|telemetry_count\|control_count\|runtime_event_count]`; sets `sessionSort.field`, resets dir → desc, re-renders | yes (parity) | no | ReplaySessionsWidget.tsx | Rebuild | |
| `rp.side.toolbar.sort.order` | leaf | button×2 | "Descending" / "Ascending" | `[data-session-sort-direction=desc\|asc]`; sets `sessionSort.direction` | yes (parity) | no | ReplaySessionsWidget.tsx | Rebuild | |
| `rp.side.list` | node | listbox | — | `#session-list.session-list`; `renderSessions()` rebuilds via `orderedSessions()` (sort field + tie-break started_at desc, then id) | yes (parity) | no | ReplaySessionsWidget.tsx | Rebuild | |
| `rp.side.list.empty` | leaf | label | "No replay sessions yet. Start the simulator/GCS and record telemetry." | shown when `sessions.length === 0` | unsure | no | ReplaySessionsWidget.tsx | Rebuild | |
| `rp.side.list.item` | node | panel | — | `article.session-item`; `.active` when `session_id === loadedSession.session_id` | yes (parity) | no | ReplaySessionsWidget.tsx | Rebuild | |
| `rp.side.list.item.select` | leaf | button | (session row) | `button.session-select`; click → `loadSession(id)` → `GET /api/replay/sessions/{id}`, loads timeline, resets map, applies frame 0. **Live (drives map)** | yes (parity) | no | ReplaySessionsWidget.tsx | Rebuild | |
| `rp.side.list.item.title` | leaf | label | "backend • <localised start>" | `strong.session-title`; `sessionLabel()` = `${backend_type} • ${new Date(started_at*1000).toLocaleString()}` | yes (parity) | no | ReplaySessionsWidget.tsx | Rebuild | |
| `rp.side.list.item.stats` | node | panel | — | `span.session-meta`; three `.session-stat` chips (inline svg + count) | yes (parity) | no | ReplaySessionsWidget.tsx | Rebuild | |
| `rp.side.list.item.stat.telemetry` | leaf | pill | telemetry frame count | `session.telemetry_count`; title "Telemetry frames" | yes (parity) | no | ReplaySessionsWidget.tsx | Rebuild | |
| `rp.side.list.item.stat.controls` | leaf | pill | control count | `session.control_count`; title "Controls" | yes (parity) | no | ReplaySessionsWidget.tsx | Rebuild | |
| `rp.side.list.item.stat.events` | leaf | pill | runtime event count | `session.runtime_event_count`; title "Events" | yes (parity) | no | ReplaySessionsWidget.tsx | Rebuild | |
| `rp.side.list.item.id` | leaf | label | session id (truncated) | `span.session-id[title=id]` | unsure | no | ReplaySessionsWidget.tsx | Rebuild | |
| `rp.side.list.item.delete` | leaf | button(icon) | trash — "Delete session <id>" | `button.ghost.session-delete`; `window.confirm` → `deleteSession()` → `DELETE /api/replay/sessions/{id}`; **disabled for the active (`currentSessionId`) session**; on delete of loaded session falls back to next telemetry-bearing session or clears | yes (parity) | no | ReplaySessionsWidget.tsx | Rebuild | not present in mission-console sidebar |

### Map playback panel (`rp.map`)

Node decision: **Redesign / `MapWidgetPanel.tsx`**. The replay-specific Leaflet map is **not** rebuilt as a separate widget — instead, track visibility, path overlay, and dual map mode ride the existing embedded Map widget's layer system (operator-console.md:84). All `rp.map.*` leaves cascade Redesign unless noted.

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `rp.map` | node | panel | "Replay" / "Map Playback" | `article.panel.replay-map-panel`; head + layer toolbar + `#replay-map` + info bar. **Replay-specific Leaflet map**, *not* the `static/map/` `MapWidget` — `ensureMap()` builds it inline in `scene` (CRS.Simple terrain) or `geo` (OSM tiles) mode | unsure (folds into Map widget? operator-console.md:84) | no | MapWidgetPanel.tsx | Redesign | replay path/track capabilities fold into MapWidget layer toggles; bespoke inline Leaflet not rebuilt |
| `rp.map.head.loaded` | leaf | pill | "No session loaded" / session id | `#loaded-session-pill.pill.warn`; set by `loadSession`/`clearReplaySelection` | yes (parity) | no | MapWidgetPanel.tsx | Redesign | surfaces as MapWidget status bar or ReplayControlsWidget header |
| `rp.map.layer-toolbar` | node | panel | "Map layers" | `.map-layer-toolbar`; six checkbox toggles | unsure (Map layer toggles, operator-console.md:84) | no | MapWidgetPanel.tsx | Redesign | folds into MapWidget's existing layer toggle system |
| `rp.map.layer.terrain` | leaf | toggle | "Terrain" | `#layer-terrain`; `layerVisibility.terrain` → re-render scene overlay | unsure | no | MapWidgetPanel.tsx | Redesign | |
| `rp.map.layer.roads` | leaf | toggle | "Roads" | `#layer-roads`; toggles scene road polylines | unsure | no | MapWidgetPanel.tsx | Redesign | |
| `rp.map.layer.objects` | leaf | toggle | "Objects" | `#layer-objects`; toggles scene object rectangles | unsure | no | MapWidgetPanel.tsx | Redesign | |
| `rp.map.layer.grid` | leaf | toggle | "Grid" | `#layer-grid`; toggles 50 m scene grid | unsure | no | MapWidgetPanel.tsx | Redesign | |
| `rp.map.layer.points` | leaf | toggle | "Telemetry Points" | `#layer-points`; toggles speed-coloured circle markers (stride-decimated to ≤500) | unsure | no | MapWidgetPanel.tsx | Redesign | |
| `rp.map.layer.path` | leaf | toggle | "Path" | `#layer-path`; toggles full+progress track lines + rover/frame markers | unsure | no | MapWidgetPanel.tsx | Redesign | |
| `rp.map.canvas` | leaf | panel | — | `#replay-map.replay-map`; Leaflet container; scene mode = CRS.Simple terrain canvas, geo mode = OSM tiles; rover marker (heading arrow) + current-frame marker + track polylines | unsure | no | MapWidgetPanel.tsx | Redesign | MapWidget already manages Leaflet; replay track/path layers added via MapWidget API |
| `rp.map.overlay` | node | panel | "Map tools" | `#map-overlay-controls.map-overlay-controls`; floating card; click/scroll propagation disabled | unsure | no | MapWidgetPanel.tsx | Redesign | |
| `rp.map.overlay.view-mode` | leaf | select | "View": Virtual Terrain / CAD/Object View / Heightmap / GPS/Satellite Debug | `#map-view-mode`; `visualMode`; change → `resetCurrentMapView()` (satellite-debug → geo map, else scene) | unsure | no | MapWidgetPanel.tsx | Redesign | |
| `rp.map.overlay.nav-mode` | leaf | select | "Nav": Free Pan / Follow Rover | `#map-nav-mode`; `navMode`; follow → `panTo` rover each frame | unsure | no | MapWidgetPanel.tsx | Redesign | |
| `rp.map.overlay.fit-terrain` | leaf | button(icon) | "Fit terrain" | `#fit-terrain`; `fitSceneMapBounds()` | unsure | no | MapWidgetPanel.tsx | Redesign | |
| `rp.map.overlay.fit-path` | leaf | button(icon) | "Fit path" | `#fit-path`; `fitCurrentPath()` → fit loaded track bounds | unsure | no | MapWidgetPanel.tsx | Redesign | |
| `rp.map.overlay.jump-rover` | leaf | button(icon) | "Jump to rover" | `#jump-rover`; `jumpToRover()` → pan to rover at current frame | unsure | no | MapWidgetPanel.tsx | Redesign | |
| `rp.map.compass` | leaf | label | "N" + mode label + "X east / Y north \| 50 m grid" | `L.Control.replay-map-compass` (scene mode only); rebuilt by `renderStaticScene()` | no | no | MapWidgetPanel.tsx | Redesign | Leaflet control; surfaced via MapWidget compass layer |
| `rp.map.info-bar` | node | panel | — | `.map-info-bar`; three readouts | unsure | no | MapWidgetPanel.tsx | Redesign | |
| `rp.map.info.cursor` | leaf | label | "Cursor: -" → scene x/y m or lat/lon | `#map-cursor`; `bindMapPointerReadout()` mousemove/mouseout | unsure | no | MapWidgetPanel.tsx | Redesign | |
| `rp.map.info.path-stats` | leaf | label | "Path: -" → samples/dist/dur/avg/max | `#map-path-stats`; `renderPathStats()` ← `calculatePathStats()` | unsure | no | MapWidgetPanel.tsx | Redesign | |
| `rp.map.info.object-detail` | leaf | label | "Selection: none" → object label/kind/xyz | `#map-object-detail`; `selectSceneObject()` on object click | unsure | no | MapWidgetPanel.tsx | Redesign | |

### Transport / playback controls (`rp.transport`)

Node decision: **Rebuild / `ReplayControlsWidget.tsx`**. All leaves cascade Rebuild.

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `rp.transport` | node | panel | — | `article.panel.replay-controls-panel`; transport row + scrubber + status banner | yes (Replay Playback Controls, operator-console.md:85) | no | ReplayControlsWidget.tsx | Rebuild | |
| `rp.transport.play-pause` | leaf | button | "Play" ↔ "Pause" | `#play-pause`; `advancePlayback()` steps frames using real inter-frame `ts` deltas ÷ speed (min 100 ms); auto-stops at last frame | yes (parity) | no | ReplayControlsWidget.tsx | Rebuild | |
| `rp.transport.seek-start` | leaf | button | "Reset" | `#seek-start.ghost`; stop + scrubber→0 + `applyPlaybackIndex(0)` | yes (parity) | no | ReplayControlsWidget.tsx | Rebuild | |
| `rp.transport.speed` | leaf | select | "Speed": 0.5x / 1x / 2x / 4x | `#replay-speed`; `speed`; scales playback delay | yes (parity) | no | ReplayControlsWidget.tsx | Rebuild | |
| `rp.transport.scrubber` | leaf | input(range) | — | `#timeline-scrubber[type=range]`; `max = telemetry.length-1`; input → stop + `applyPlaybackIndex` | yes (parity) | no | ReplayControlsWidget.tsx | Rebuild | |
| `rp.transport.status` | leaf | label | "Load a session to begin replay." → "Frame N/T • <ts> • <speed>x • <map> • <mode>" | `#timeline-status.status-banner`; also surfaces load/init errors | yes (parity) | no | ReplayControlsWidget.tsx | Rebuild | |

### Telemetry snapshot panel (`rp.telemetry`)

Node decision: **Redesign / `TelemetryWidget.tsx`**. Live `TelemetryWidget` exists; Pass B decision = extend it with a replay-frame prop rather than rebuild a separate panel. All leaves cascade Redesign.

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `rp.telemetry` | node | panel | "Telemetry Snapshot" | `article.panel.replay-telemetry-panel`; `dl.stats` of 6 readouts, set by `renderTelemetry(frame.payload)` | unsure (telemetry widget exists; replay-bound variant?) | partial: live `TelemetryWidget` exists, not replay-frame-bound | TelemetryWidget.tsx | Redesign | extend TelemetryWidget with optional replay-frame binding via prop; no separate panel |
| `rp.telemetry.pos` | leaf | label | "Position": x y z | `#replay-pos` | unsure | no | TelemetryWidget.tsx | Redesign | |
| `rp.telemetry.speed` | leaf | label | "Speed": km/h \| m/s | `#replay-speed-card` | unsure | no | TelemetryWidget.tsx | Redesign | |
| `rp.telemetry.heading` | leaf | label | "Heading": deg | `#replay-heading` ← `orientation.heading_deg` | unsure | no | TelemetryWidget.tsx | Redesign | |
| `rp.telemetry.gps` | leaf | label | "GPS": lat, lon, alt | `#replay-gps` | unsure | no | TelemetryWidget.tsx | Redesign | |
| `rp.telemetry.camera` | leaf | label | "Camera": mode \| endpoint | `#replay-camera` | unsure | no | TelemetryWidget.tsx | Redesign | |
| `rp.telemetry.power` | leaf | label | "Power": battery% \| V \| A \| C | `#replay-power` | unsure | no | TelemetryWidget.tsx | Redesign | |

### Records panel (`rp.records`)

Node decision: **Defer**. The multi-tab tabular log viewer is lower priority than sessions/transport/map. All leaves cascade Defer.

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `rp.records` | node | panel | "Replay Records" | `article.panel.replay-events-panel`; tabs + list | unsure | no | ReplayRecordsWidget.tsx | Defer | |
| `rp.records.tabs` | node | tablist | "Replay record type" | `.record-tabs[role=tablist]`; click toggles `recordView` + `.active`, re-renders | unsure | no | ReplayRecordsWidget.tsx | Defer | |
| `rp.records.tab.telemetry` | leaf | tab | "Telemetry Frames" | `#records-telemetry[data-record-view=telemetry]` (default active); `telemetryRecordLine()` | unsure | no | ReplayRecordsWidget.tsx | Defer | |
| `rp.records.tab.controls` | leaf | tab | "Controls" | `#records-controls[data-record-view=controls]`; `controlRecordLine()` (active buttons / source) | unsure | no | ReplayRecordsWidget.tsx | Defer | |
| `rp.records.tab.events` | leaf | tab | "System Events" | `#records-events[data-record-view=events]`; `eventRecordLine()` (type / level) | unsure | no | ReplayRecordsWidget.tsx | Defer | |
| `rp.records.tab.all` | leaf | tab | "All Timeline" | `#records-all[data-record-view=all]`; merges all three sorted by ts | unsure | no | ReplayRecordsWidget.tsx | Defer | |
| `rp.records.list` | leaf | listbox | — | `#event-list.event-list`; `renderReplayRecords()` last 150 reversed; empty → "No records" | unsure | no | ReplayRecordsWidget.tsx | Defer | |

### Cross-cutting behaviors

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `rp.behavior.timezone-header` | leaf | (behavior) | — | `withReplayTimezone()` adds `X-Operator-Timezone` (resolved tz) to every replay fetch | no | no | ReplaySessionsWidget.tsx | Rebuild | part of fetch layer in ReplaySessionsWidget or shared hook |
| `rp.behavior.scene-map-load` | leaf | (behavior) | — | `loadSceneMap()` → `GET /api/replay/scene-map?backend=3d-env&grid_size=128`; failure → null → geo-map fallback | unsure | no | MapWidgetPanel.tsx | Redesign | folds into MapWidget's existing scene-map loading |
| `rp.behavior.dual-map-mode` | node | (behavior) | — | `ensureMap('scene'\|'geo')`: scene = `CRS.Simple` virtual terrain (canvas heightmap, roads, objects, grid, compass); geo = OSM tiles by georeference origin. `visualMode='satellite-debug'` forces geo | unsure (Map widget already does scene/geo? see map.md) | no | MapWidgetPanel.tsx | Redesign | folds into MapWidget view-mode system; no separate Leaflet instance |
| `rp.behavior.gps-to-scene` | leaf | (behavior) | — | `scenePointFromGps()` converts GPS→local scene XY via georeference (earth-radius equirectangular) when telemetry lacks `position` | no | no | replay data layer | Rebuild | utility function in replay hooks/store |
| `rp.behavior.persisted-layout` | leaf | (behavior) | — | sidebar width + pane height persisted to localStorage (`gcs-replay-sidebar-width`, `gcs-replay-pane-height`); desktop-only | no | no | — | Drop | dockview owns layout persistence |

## 2. Style appendix (lossless backstop)

Values keyed by `id`; `@ style.css:<line>` is the authoritative source. Node rows
carry layout; leaf rows carry appearance. Shared session-sidebar tokens overlap
`mission-console.md`'s appendix (same classes) — repeated here with replay-only
additions (sort popover, delete, split panes, map/transport).

### Layout (nodes)

- `rp.shell` — `.replay-shell` grid `gap:0`. `@ style.css:473`
- `rp.split-pane` — `.replay-split-pane` grid `minmax(260px,var(--replay-sidebar-width)) 6px minmax(0,1fr)` × `minmax(0,1fr) auto`; areas `"sidebar divider map" / ". . controls"`; `row-gap:10px`; `height:var(--replay-pane-height)`. Defines `--replay-sidebar-width:344px`, `--replay-pane-height:760px`, `--replay-card-radius:18px`, `--replay-card-shadow`. `@ style.css:478`
- `rp.split-divider` — `.replay-split-divider` `grid-area:divider`; centered handle; `cursor:col-resize`. `@ style.css:1909`; handle `@ style.css:1939`; `.is-resizing` line accent `@ style.css:1945`
- `rp.height-divider` — `.replay-height-divider` row separator; `cursor:row-resize`. `@ style.css:1983`; handle `@ style.css:2010`
- `rp.side` — `.replay-sidebar` `grid-area:sidebar`; flex column; `gap:12px`; `height:100%`; `overflow:hidden`; `padding:12px 6px 12px 12px`; `border:1px color-mix(--line 64%)`; `border-radius:var(--replay-card-radius)`; `background:color-mix(--panel 88%,--panel-strong)`; `box-shadow:var(--replay-card-shadow)`. `@ style.css:1600`; head `.session-head-top` `@ style.css:1628`; `.panel-head` `@ style.css:1619`
- `rp.side.toolbar` — `.session-toolbar` flex; `align-items:center`; `justify-content:flex-end`; `gap:8px`; `padding:0 6px 0 0`. `@ style.css:1863`
- `rp.side.toolbar.sort` — `.session-sort-control` `position:relative`. `@ style.css:1640`; popover `.session-sort-popover` `position:absolute`; card with `--line` border + shadow `@ style.css:1680`
- `rp.side.list` — `.replay-sidebar .session-list` `flex:1 1 auto`; `min-height:0`; `gap:8px`; `overflow-y:auto`; `padding:0 4px 4px 0`; `scrollbar-gutter:stable`; `overscroll-behavior:contain` (base `.session-list` grid `gap:18px` @455). `@ style.css:1871`
- `rp.side.list.item` — `.session-item` grid `minmax(0,1fr) 30px`; `gap:8px`; `align-items:center`; `padding:10px`; `border-radius:10px`; `background:color-mix(--panel-strong 54%)`; `border:1px color-mix(--line 52%)`. `.active`→accent border + `color-mix(--accent-soft 34%,--panel-strong)` `@ style.css:2051`; hover `@ style.css:2056`. `@ style.css:2038`
- `rp.side.list.item.stats` — `.session-meta` flex-wrap; `gap:8px`; `align-items:center`. `@ style.css:2111`
- `rp.map` — `.replay-map-panel` `grid-area:map`; flex column; min-height for map. `@ style.css:800`
- `rp.map.layer-toolbar` — `.map-layer-toolbar` flex-wrap toggles row; `gap`; small labels. `@ style.css:814`
- `rp.map.canvas` — `.replay-map` `grid-area`/fill; `border-radius`; `.replay-map.leaflet-container` background `@ style.css:1495`. `@ style.css:1365`
- `rp.map.overlay` — `.map-overlay-controls` `position:absolute`; floating; stacked cards. `@ style.css:1196`; `.map-overlay-card` `@ style.css:1208`; `.map-overlay-selects` `@ style.css:1218`; `.map-fit-actions` `@ style.css:1274`
- `rp.map.info-bar` — `.map-info-bar` flex row of readouts; muted small text. `@ style.css:1379`
- `rp.transport` — `.replay-controls-panel` `grid-area:controls`; panel; flex column. `@ style.css:1883`; `.transport-row` flex `justify-content:space-between` `@ style.css:2184`; `.transport-actions` flex `gap` `@ style.css:2193`
- `rp.telemetry` — `.replay-telemetry-panel` panel; `dl.stats` grid `@ style.css:681`. `@ style.css:1884`
- `rp.records` — `.replay-events-panel` panel; `.event-list` grid `gap:18px` `@ style.css:456`. `@ style.css:1885`
- `rp.records.tabs` — `.record-tabs` flex tab row. `@ style.css:2155`
- `rp.bottom-grid` — `.replay-bottom-grid` grid `minmax(0,1.05fr) minmax(300px,0.95fr)`; `margin-top:18px`. `@ style.css:498`

### Appearance (leaves)

- `rp.side.head.{count,current}` — `.session-head-meta .pill` `padding:4px 10px`; `background:color-mix(--panel-strong 92%)`; `border:1px color-mix(--line 42%)`. Container `.session-head-meta` inline-flex wrap `@ style.css:1840`. Base `.pill` `@ style.css:553`
- `rp.map.head.loaded` — `.pill.warn` warn-tint variant of `.pill`. `@ style.css:567`
- `rp.side.toolbar.{refresh,rollover}` — `.replay-session-icon-btn` 34×34; `border-radius:10px`; svg 16px `fill:currentColor`; `background:color-mix(--panel-strong 72%)`; `border:1px color-mix(--line 74%)`; hover→accent; rollover (`:last-child`) `color:var(--accent)`; CSS `::after` tooltip from `data-tooltip`. `@ style.css:1762`
- `rp.side.toolbar.sort.trigger` — `.replay-sort-trigger` ghost icon button + inline `.session-sort-summary` text. `@ style.css:1645`
- `rp.side.toolbar.sort.{field,order}` — `.session-sort-menu-item` full-width menu button; `.active`→accent. `@ style.css:1719`
- `rp.side.list.item.select` — `.session-select` `width:100%`; `text-align:left`; grid `gap:4px`; transparent button. `@ style.css:2061`
- `rp.side.list.item.title` — `.session-title` `display:block`; `font-size:.95rem`; `font-weight:650`; `line-height:1.2`. `@ style.css:2103`
- `rp.side.list.item.stat.*` — `.session-stat` inline-flex; `gap:5px`; `padding:2px 6px`; `border-radius:999px`; `background:color-mix(--panel-strong 70%)`; `border:1px color-mix(--line 68%)`; svg 12px `opacity:.9`. `.session-item.active .session-stat`→accent `@ style.css:2136`. `@ style.css:2118`
- `rp.side.list.item.id` — `.session-id` ellipsis; `white-space:nowrap`; `overflow:hidden`. `@ style.css:2148`
- `rp.side.list.item.delete` — `.session-delete` ghost icon button (30px col); trash svg; `:disabled` dimmed (active session). `@ style.css:2081`
- `rp.map.overlay.{view-mode,nav-mode}` — `.map-overlay-selects label` icon (`.map-tool-icon` @1234) + `.map-tool-label` (@1250) + native `<select>`; card-tinted. `@ style.css:1218`
- `rp.map.overlay.{fit-terrain,fit-path,jump-rover}` — `.map-tool-button` icon button; svg sized `@ style.css:1235`. `@ style.css:1274` (`.map-fit-actions` container)
- `rp.map.compass` — `.replay-map-compass` Leaflet control card; `<strong>N</strong>` + `.compass-arrow` + `<small>`. `@ style.css:1557`
- `rp.map.canvas` markers — `.rover-marker-icon` + `.rover-heading-arrow` (rotated arrow) `@ style.css:1432,1437`; `.current-frame-icon` pulse dot `@ style.css:1467`
- `rp.transport.{play-pause,seek-start}` — base `button` + `.ghost` variant for Reset (shared button styles).
- `rp.transport.speed` — `.speed-control` flex label + `<select>`; `.replay-controls-panel .speed-control` `@ style.css:2199`
- `rp.transport.scrubber` — `#timeline-scrubber` styled range input (track/thumb). `@ style.css:2242`
- `rp.transport.status` / `rp.records.list.empty` — `.status-banner` muted info banner `@ style.css:709`; `.event-row` record row `@ style.css:692`; `.section-kicker` `@ style.css:334`; `.panel` `@ style.css:296`; `.panel-head` `@ style.css:541`
- `rp.telemetry.*` — `dl.stats` `dt`/`dd` pairs (`.stats` @681)
- `rp.records.tab.*` — `.record-tab` tab button; `.active` underline/accent (`.record-tabs` @2155)

### Theme tokens (resolve in `style.css` `:root`/`[data-theme]`)

`--accent`, `--accent-soft`, `--line`, `--muted`, `--text`, `--panel`,
`--panel-strong`, `--bg-base`, `--replay-card-radius`, `--replay-card-shadow`,
`--replay-sidebar-width`, `--replay-pane-height`. Scene render colours (terrain
ramp, object kinds, speed ramp, grid) are **hard-coded in `replay.js`**, not CSS:
`terrainColorForNormalizedHeight()` @209, `sceneObjectStyle()` @351,
`speedColor()` @367, grid `#496070`/`#f6efe4` @1109.
