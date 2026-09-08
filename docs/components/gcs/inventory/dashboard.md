# Dashboard / index page inventory — `static/index.html` + `static/app.js`

Pass A extraction (mechanical). Source: `backend/static/index.html` (119 lines),
`backend/static/app.js` (712 lines), shared shell `backend/static/common.js`
(174 lines), styles in `backend/static/style.css`. Target app: `frontend/` —
present widgets are `AIChatWidget.tsx`, `MapWidgetPanel.tsx`, `ClockWidget`,
`DriveControlsWidget`, `NotesWidget`, `TelemetryWidget`, `VideoWidget`.

**This is the original single-screen operator dashboard:** a 3-panel grid —
**Video Feed** (with a telemetry OSD overlay), **Controls & Connection** (broker/
rover/control pills + a touch d-pad + keyboard driving), and **Telemetry &
Runtime** (a 12-field stat sheet). Served at `/` and `/dashboard` (body
`data-page="dashboard"`). Almost everything is static HTML whose **text content**
is updated in place by `app.js`; the only DOM *created* at runtime is the shared
header/intro injected by `common.js` `initShell()`.

The dashboard's three panels map cleanly to **already-built** greenfield widgets
(`VideoWidget`, `DriveControlsWidget`, `TelemetryWidget`), so most rows read
`partial`/`yes` on `implemented?` — the real gaps are the **video OSD overlay**
(absent in `VideoWidget`) and the **connection-indicator strip** (broker/rover
pills have no dashboard panel in the new app). The shared page **header/nav/intro**
shell is superseded by the dockview workspace shell and is not a per-page widget.

`planned?` / `implemented?` pre-filled. `target` and `decision` are intentionally
blank — filled in **Pass B (INV-B)**.

**Pre-fill key.** `planned?`: the new design doc
([operator-console.md](../design/operator-console.md)) widget table lists **Video
Feed** ("OSD overlay is a bound sub-part; WS-subscription-gated", line 79), **Drive
Controls** ("singleton; owns key capture when focused", line 80), **Telemetry /
Runtime** ("pure read view", line 81), and **Status Bar** (line 86); line 141 calls
out Video, Drive Controls (touch d-pad), Telemetry, and AI Chat as the responsive
set. So those rows read **yes**. The **broker/rover/control-state pills** have no
dedicated widget — design folds broker/controller into the shared runtime store and
a singleton Status Bar — so the connection strip reads **unsure**. The page
**header/nav** is replaced by the workspace shell, so it reads **no**.
`implemented?`: searched `frontend/src/` — `VideoWidget.tsx` (img + empty + a
live/mode status line, **no OSD**), `TelemetryWidget.tsx` (6-field subset of the
stat sheet), `DriveControlsWidget.tsx` (d-pad + key capture + ownership) all exist;
**no** OSD overlay, **no** connection-indicators panel, **no** per-page header/nav.

## 1. Decision table

### Page shell & layout (shared `common.js` `initShell`)

The header, nav, and page-intro are injected by `common.js` on every page; they are
inventoried here once. Identical rows recur on `ai`/`replay`/`settings`/
`mission-console`.

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `db` | node | panel | — | Page root `body[data-page="dashboard"]` → `main.app-shell[data-app-shell]`; stacks injected header → `data-page-intro` → `section.page-grid.dashboard-grid` (3 panels) | yes (single-screen operator view, operator-console.md:141) | partial (panels exist as separate dockview widgets, no fixed page) | `workspace` | Drop | Layout artifact; panels compose in dockview; no fixed page shell |
| `db.header` | node | panel | — | `header.app-header` built by `initShell()`; sticky top; `app-header-inner` = brand + nav | no (workspace shell replaces per-page header) | no | — | Drop | Workspace shell replaces per-page header |
| `db.header.brand` | leaf | label/link | "Ground Control Station" / "Remote Rover GCS" | `a.app-brand[href="/mission-console"]`; kicker + strong title | no | no | — | Drop | |
| `db.header.nav` | node | panel | — | `nav.app-nav`; 5 links, active = current page | no (dockview tab/menu replaces nav) | no | — | Drop | |
| `db.header.nav.link` | leaf | link ×5 | "Mission Console" / "Dashboard" / "Replay" / "AI Chat" / "Settings" | `a.app-nav-link[href=/…]`; `.active`+`aria-current` when `page` matches | no | no | — | Drop | |
| `db.intro` | leaf | panel | "Dashboard" + lede | `data-page-intro` filled by `initShell()` with kicker/h2 + lede "Browser-based monitoring and low-latency manual control for the rover simulator." | no | no | — | Drop | |

### Video Feed panel

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `db.video` | node | panel | "Video Feed" | `article.panel.video-panel` (grid-area `video`); head (title + mode pill) + frame wrap | yes (Video Feed widget, operator-console.md:79) | yes (`VideoWidget.tsx`) | `VideoWidget.tsx` | Keep | Widget exists; wiring complete |
| `db.video.mode-pill` | leaf | pill | "MQTT -> WebSocket" / "`<ingest>` -> `<delivery>`" / "Disabled" | `#video-mode-pill`; `updateVideoMode()` from snapshot/WS `video.{ingest_mode,delivery_mode,enabled}` | yes | partial: `VideoWidget` shows `delivery_mode`/"disabled" only, not `ingest -> delivery` | `VideoWidget.tsx` | Rebuild | Show full `ingest → delivery` format; may reflect recent bug fix — verify |
| `db.video.frame-wrap` | node | panel | — | `div.video-frame-wrap`; positioned container for img + OSD + empty-state | yes | yes | `VideoWidget.tsx` | Keep | |
| `db.video.frame` | leaf | img | (rover feed) | `#video-frame`; `updateVideoFrame()` sets `src=data:<mime>;base64,<data>` from `video_frame` WS msg / `video.latest_frame`; hidden until first frame | yes | yes (`VideoWidget` img ref, same data-URI path) | `VideoWidget.tsx` | Keep | |
| `db.video.osd` | node | panel | "Telemetry overlay" | `div.video-osd[aria-label]`; absolute top-right overlay, 5 monospace lines; `pointer-events:none` | yes (OSD is a bound sub-part, operator-console.md:79) | no (`VideoWidget` has no overlay) | `VideoWidget.tsx` | Rebuild | Key gap — OSD overlay absent in VideoWidget; 5 telemetry lines at top-right |
| `db.video.osd.position` | leaf | label | "position x:+00.00 y:+00.00 z:+0.00" | `#osd-line-position`; `telemetryOsdPosition()` signed-padded x/y/z | yes | no | `VideoWidget.tsx` | Rebuild | Cascades from osd |
| `db.video.osd.speed` | leaf | label | "speed 0.0 km/h (0.00 m/s) heading 0.0 deg" | `#osd-line-speed`; `telemetryOsdSpeed()` speed + heading | yes | no | `VideoWidget.tsx` | Rebuild | |
| `db.video.osd.gps` | leaf | label | "gps lat:0.000000 lon:0.000000 alt:0.00 m" | `#osd-line-gps`; `telemetryOsdGps()` | yes | no | `VideoWidget.tsx` | Rebuild | |
| `db.video.osd.power` | leaf | label | "power batt:0% 0.00V 0.0A 0.0C" | `#osd-line-power`; `telemetryOsdPower()` | yes | no | `VideoWidget.tsx` | Rebuild | |
| `db.video.osd.camera` | leaf | label | "camera mode:- endpoint:- rx:no data" | `#osd-line-camera`; `telemetryOsdCamera()` mode/endpoint + rx-age | yes | no | `VideoWidget.tsx` | Rebuild | |
| `db.video.empty` | leaf | label | "Waiting for camera frames on MQTT." | `#video-empty`; hidden once a frame arrives | yes | yes (`VideoWidget` "Waiting for video…") | `VideoWidget.tsx` | Keep | |

### Controls & Connection panel

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `db.controls` | node | panel | "Controls & Connection" | `article.panel.controls-panel` (grid-area `controls`); flex column: control-state row, connection indicators, hint, d-pad, status banner | yes (Drive Controls widget, operator-console.md:80) | partial (`DriveControlsWidget` covers d-pad/keys/ownership; no connection strip) | `DriveControlsWidget.tsx` | Keep | Widget covers d-pad + key capture + ownership; connection strip handled separately |
| `db.controls.state-row` | node | panel | "Browser Control" | `div.indicator-row.control-state-row` inside `.inline-actions` | unsure | partial (ownership shown inside `DriveControlsWidget`, not a pill row) | `DriveControlsWidget.tsx` | Redesign | Ownership state is already surfaced inside the widget; shape differs — keep the widget's own treatment |
| `db.controls.state-pill` | leaf | pill | "Inactive" / "Activating" / "Deactivating" / "Active" / "Other Browser Active" | `#control-state-pill`; `renderControlToggle()` from owner vs `clientId` + pending; tone warn/ok | yes (control ownership UX) | partial (`DriveControlsWidget` renders an owner/acquire state, different shape) | `DriveControlsWidget.tsx` | Redesign | Reconcile pill states (Inactive/Activating/Active/Other) with widget's current ownership display |
| `db.controls.connection` | node | panel | "Connection indicators" | `div.connection-indicators`; two rows (broker, rover) | unsure (design folds broker/controller into runtime store + Status Bar) | no (no connection panel in new app) | `workspace` | Redesign | Broker + rover availability → workspace status bar / status surface, not a dedicated panel |
| `db.controls.broker-pill` | leaf | pill | "Connecting" / "Connected" / "Disconnected" | `#broker-pill`; `renderBrokerIndicator()` from snapshot/WS `broker.{connected,status}` | unsure | partial (broker status surfaced as a line in Video/Telemetry widgets, no pill) | `workspace` | Redesign | Fold into workspace status bar pill; runtime store already tracks broker state |
| `db.controls.rover-pill` | leaf | pill | "No data" / "Connected" / "`N`s delayed" / "Unavailable" | `#rover-pill`; `renderRoverIndicator()` from telemetry age vs `rover_availability` thresholds | unsure | no | `workspace` | Redesign | Fold into workspace status bar; rover availability thresholds are in config |
| `db.controls.hint` | leaf | label | "Use arrow keys or W/A/S/D. Control is active only while this dashboard tab is visible and focused." | static `p.hint` | yes (driving help) | no | `DriveControlsWidget.tsx` | Rebuild | Add driving hint text to DriveControlsWidget; may have landed with bug fixes — verify |
| `db.controls.dpad` | node | panel | — | `div.dpad`; Forward on top, then row Left/Backward/Right; `bindControlButtons()` mouse/touch press→`state.buttons[ctrl]`→`sendControlState()` (WS `{type:control}`); `.active` class on press | yes (touch d-pad, operator-console.md:141) | yes (`DriveControlsWidget` d-pad) | `DriveControlsWidget.tsx` | Keep | |
| `db.controls.dpad.forward` | leaf | button | "Forward" | `button.control-btn[data-control=forward]` | yes | yes | `DriveControlsWidget.tsx` | Keep | |
| `db.controls.dpad.left` | leaf | button | "Left" | `button.control-btn[data-control=left]` | yes | yes | `DriveControlsWidget.tsx` | Keep | |
| `db.controls.dpad.backward` | leaf | button | "Backward" | `button.control-btn[data-control=backward]` | yes | yes | `DriveControlsWidget.tsx` | Keep | |
| `db.controls.dpad.right` | leaf | button | "Right" | `button.control-btn[data-control=right]` | yes | yes | `DriveControlsWidget.tsx` | Keep | |
| `db.controls.status-banner` | leaf | label | "Connecting to GCS runtime." (+ live status text) | `#status-banner`; `setStatus()` reflects socket/control state changes & errors | unsure (status surface; design has singleton Status Bar) | no | `workspace` | Redesign | Fold into workspace status bar |

### Telemetry & Runtime panel

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `db.telemetry` | node | panel | "Telemetry & Runtime" | `article.panel.telemetry-panel` (grid-area `telemetry`, full width); `dl.stats` 2-col grid of 12 dt/dd cards | yes (Telemetry/Runtime, operator-console.md:81) | partial (`TelemetryWidget` shows a 6-field subset) | `TelemetryWidget.tsx` | Rebuild | Expand from 6-field subset to full 12-field stat sheet |
| `db.telemetry.controller` | leaf | label | "Unclaimed" / "This browser" / "Another browser" / "Inactive" | `#controller-owner`; `updateController()` from `controller.active_client_id` vs `clientId` | yes | no | `TelemetryWidget.tsx` | Rebuild | Controller ownership field missing from TelemetryWidget |
| `db.telemetry.client-id` | leaf | label | (uuid) | `#client-id`; set once from `state.clientId` | unsure | no | — | Drop | Internal UUID; no user-facing value |
| `db.telemetry.telemetry-freshness` | leaf | label | "No data" / "Fresh" / "Stale" | `#telemetry-freshness`; from `broker.telemetry_stale` | yes | no | `TelemetryWidget.tsx` | Rebuild | Telemetry freshness field missing |
| `db.telemetry.camera-freshness` | leaf | label | "No data" / "Fresh" / "Stale" | `#camera-freshness`; from `broker.camera_stale` | yes | no | `TelemetryWidget.tsx` | Rebuild | Camera freshness field missing |
| `db.telemetry.backend` | leaf | label | "-" / "`<backend> (<version>)`" | `#simulation-backend`; `updateSimulation()` from `simulation.{backend,backend_version}` | yes | yes (`TelemetryWidget` "Backend" row) | `TelemetryWidget.tsx` | Keep | |
| `db.telemetry.last-received` | leaf | label | "No data" / "`<age>` ago (`<time>`)" | `#telemetry-last-received`; `renderTelemetryLastReceived()` re-ticks every 1s | yes | no | `TelemetryWidget.tsx` | Rebuild | 1 s tick readout missing; important for staleness awareness |
| `db.telemetry.pos` | leaf | label | "-" / "x y z" | `#pos`; `telemetryCardPosition()` | yes | no | `TelemetryWidget.tsx` | Rebuild | Position field missing |
| `db.telemetry.speed` | leaf | label | "-" / "`N` km/h \| `N` m/s" | `#speed`; `telemetryCardSpeed()` | yes | yes (`TelemetryWidget` "Speed km/h") | `TelemetryWidget.tsx` | Keep | |
| `db.telemetry.heading` | leaf | label | "-" / "`N` deg" | `#heading`; `telemetryCardHeading()` | yes | yes (`TelemetryWidget` "Heading °") | `TelemetryWidget.tsx` | Keep | |
| `db.telemetry.gps` | leaf | label | "-" / "lat, lon, alt `N`m" | `#gps`; `telemetryCardGps()` | yes | yes (`TelemetryWidget` "GPS", gated on `validity.has_gps`) | `TelemetryWidget.tsx` | Keep | |
| `db.telemetry.camera-mode` | leaf | label | "-" / "`<mode>` \| `<endpoint>`" | `#camera-mode`; `telemetryCardCamera()` | yes | no | `TelemetryWidget.tsx` | Rebuild | Camera mode/endpoint field missing |
| `db.telemetry.power` | leaf | label | "-" / "`N`% \| `N`V \| `N`A \| `N`C" | `#power`; `telemetryCardPower()` (battery/voltage/current/temp) | yes | partial (`TelemetryWidget` shows Battery % + Voltage V only) | `TelemetryWidget.tsx` | Rebuild | Add current (A) + temperature (C) to power card |

### Cross-cutting behaviors

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `db.behavior.snapshot` | node | (behavior) | — | `loadSnapshot()` → `GET /api/snapshot` seeds broker/controller/telemetry/video/simulation/`rover_availability` before WS | yes (data layer, operator-console.md §data) | yes (runtime store `/ws` snapshot) | `data/runtimeStore.ts` | Keep | |
| `db.behavior.ws` | node | (behavior) | — | `connectSocket()` → `/ws?client_id=…`; dispatches `snapshot`/`telemetry`/`simulation_config`/`broker`/`controller`/`video_frame`/`video`/`error` | yes | yes (`wsClient` runtime store) | `data/runtimeStore.ts` | Keep | |
| `db.behavior.control-take` | leaf | (behavior) | — | `setControlEnabled()` → `POST /api/controller/{take,release}` on focus/blur/visibility; auto-acquires while tab focused | yes | yes (`DriveControlsWidget` ownership) | `DriveControlsWidget.tsx` | Keep | |
| `db.behavior.keyboard` | leaf | (behavior) | — | `bindKeyboard()`: keydown/keyup arrows+WASD → control while `canControlLocally()`; preventDefault; focus/blur/visibility re-sync | yes (key capture, operator-console.md:80) | yes (`DriveControlsWidget`) | `DriveControlsWidget.tsx` | Keep | |
| `db.behavior.keybinds` | leaf | (behavior) | — | `loadControlConfig()` → `GET /api/config`; `key_bindings` remap d-pad keys, else `DEFAULT_KEY_TO_CONTROL` | yes | yes (`DriveControlsWidget` `normalizeConfiguredKey`/`keyMapFromBindings`, same logic) | `DriveControlsWidget.tsx` | Keep | |
| `db.behavior.theme` | leaf | (behavior) | — | Inline `<head>` script + `initTheme()` apply `data-theme*` from localStorage; dashboard has **no** theme controls (`syncThemeControls` no-op); follows system on `system` mode | no (theme is a workspace/app-shell concern) | partial (greenfield has its own theming) | `workspace` | Drop | Theming is a workspace/shell concern; greenfield has its own theme layer |

## 2. Style appendix (lossless backstop)

Values keyed by `id`; `@ style.css:<line>` is the authoritative source. Node rows
carry layout; leaf rows carry appearance. Shared shell + `.panel`/`.pill` tokens are
listed once here (they recur on every page).

### Layout (nodes)

- `db` — `.app-shell` `width:min(1440px, calc(100vw - 32px))`; `margin:0 auto`; `padding:18px 0 40px`. `@ style.css:289`
- `db` grid — `.page-grid` base grid `gap:18px` `@ style.css:450`; `.dashboard-grid` `grid-template-columns:minmax(0,1.7fr) 380px`; areas `"video controls" / "telemetry telemetry"`; `align-items:start` `@ style.css:461`. Mobile (≤ breakpoint) collapses to 1col, areas stack `video`→`controls`→`telemetry` `@ style.css:6104,6115`.
- `db.header` — `.app-header` sticky `top:12px`; `z-index:30`; `border-radius:22px`; `margin-bottom:18px` (16px with intro `@312`); shares `.app-header,.panel,.page-intro` `background:var(--panel)` + `1px var(--line)` + `var(--shadow)` + `backdrop-filter:blur(16px)` `@295`. `@ style.css:304`
- `db.header.brand` — `.app-brand` grid `gap:2px`; kicker `.app-brand-kicker` `color:var(--accent)`; `font-size:.78rem`; `letter-spacing:.16em`; uppercase `@332`; `strong` `clamp(1.6rem,2.4vw,2.2rem)` `@343`. `@ style.css:325`
- `db.header.nav` — `.app-nav` `flex:1 1 520px`; flex end; `gap:10px`; wrap; `padding:8px`; `border-radius:20px`; gradient bg + inset shadows. `@ style.css:349`
- `db.intro` — `.page-intro` `border-radius:24px`; `padding:24px`; `margin-bottom:18px`; `h2` `clamp(1.35rem,2.6vw,1.85rem)` `@419`; `.page-lede` `max-width:68ch`; `color:var(--muted)` `@426`. `@ style.css:407`
- `db.video` — `.video-panel` `grid-area:video` `@516`; `.panel` `border-radius:20px`; `padding:18px` `@532`.
- `db.video.frame-wrap` — `.video-frame-wrap` `position:relative`; `min-height:420px`; `border-radius:18px`; `overflow:hidden`; subtle top→bottom tint; `1px color-mix(--line 85%)`. `@ style.css:633`
- `db.video.osd` — `.video-osd` `position:absolute`; `top:22px`; `right:22px`; `z-index:2`; flex column; `gap:8px`; `max-width:min(48%,440px)`; `pointer-events:none`. `@ style.css:649`
- `db.controls` — `.controls-panel` `grid-area:controls` `@524`; `.controls-panel`/`.status-panel` flex column `@717`; `.panel-head{margin-bottom:10px}` `@727`; `.inline-actions{margin-bottom:12px}` `@723`.
- `db.controls.connection` — `.connection-indicators` grid `gap:10px`; `margin-bottom:14px`. `@ style.css:736`
- `db.controls.dpad` — `.dpad` flex column center `gap:10px`; `margin-top:14px` `@753`; `.dpad-row` flex `gap:10px` `@761`.
- `db.telemetry` — `.telemetry-panel` `grid-area:telemetry` (full-width row) `@520`; `.stats` grid `repeat(2,minmax(0,1fr))`; `gap:14px 18px` `@681`; each `.stats div` `padding:12px`; `border-radius:14px`; faint bg + `1px color-mix(--line 70%)` `@691`.
- `db.panel-head` — `.panel-head` flex space-between; `align-items:flex-start`; `gap:16px`; `margin-bottom:16px`. `@ style.css:541`

### Appearance (leaves)

- `db.header.nav.link` — `.app-nav-link` shares button base `padding:11px 16px`; `border-radius:14px`; `1px var(--line)`; `var(--button-secondary-gradient)` `@369`; `.active` accent gradient `var(--tab-active-*)` + raised shadow `@393`; hover `translateY(-1px)` + accent border `@606`; focus 3px accent ring `@616`. `@ style.css:387`
- `db.*.pill` (`mode-pill`, `state-pill`, `broker-pill`, `rover-pill`) — `.pill` `padding:6px 10px`; `border-radius:999px`; `background:var(--button-secondary-bg)`; `color:var(--muted)`; `font-size:.85rem`; `white-space:nowrap` `@553`. Tones: `.ok`→`--accent-strong`/`--ok-bg` `@562`; `.warn`→`--warn`/`--warn-bg` `@567`; `.danger`→`--danger`/`--danger-bg` `@572`.
- `db.video.frame` — `#video-frame` `width:100%`; `height:100%`; `object-fit:cover`; `display:none` until first frame. `@ style.css:642`
- `db.video.osd.*` — `.video-osd-line` `color:#ffffff`; `font-family:"IBM Plex Mono",…monospace`; `font-size:clamp(.74rem,1.2vw,.92rem)`; `line-height:1.25`; layered text-shadow for legibility; `word-break:break-word`. `@ style.css:661`
- `db.video.empty` — `.video-empty` `position:absolute`; `inset:0`; grid place-items center; `color:var(--muted)`. `@ style.css:673`
- `db.controls.state-row` / `db.controls.connection` rows — `.indicator-row` flex space-between; `gap:12px`; `padding:10px 12px`; `border-radius:14px`; faint bg + `1px color-mix(--line 70%)`. `@ style.css:742`
- `db.controls.hint` / `db.controls.status-banner` — `.hint`/`.status-banner` `color:var(--muted)`; `margin-top:16px`; `line-height:1.45` `@709`; `.controls-panel .hint{margin-top:0;font-size:.9rem}` `@731`.
- `db.controls.dpad.*` — `.control-btn` `min-width:96px`; `min-height:62px`; `padding:10px 12px`; `var(--button-control-gradient)` `@766`; `.active`→accent border + `var(--button-active-strong-gradient)` + `translateY(1px)` `@773`.
- `db.telemetry.*` — `.stats dt` `color:var(--muted)`; `font-size:.85rem`; `margin-bottom:6px` `@699`; `.stats dd` `margin:0` `@705`.

### Theme tokens (resolve in `style.css` `:root`/`[data-theme]`)

`--accent`, `--accent-strong`, `--line`, `--muted`, `--text`, `--panel`,
`--panel-strong`, `--bg-base`, `--shadow`, `--button-secondary-bg`,
`--button-secondary-gradient`, `--button-control-gradient`,
`--button-active-strong-gradient`, `--ok-bg`, `--warn`, `--warn-bg`, `--danger`,
`--danger-bg`, `--tab-active-top`, `--tab-active-bottom`, `--tab-active-border`,
`--tab-active-shadow`.
