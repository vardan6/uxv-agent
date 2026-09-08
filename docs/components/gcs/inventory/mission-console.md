# Mission Console page inventory — `static/mission-console.html` + `static/mission-console.js`

Pass A extraction (mechanical). Source: `backend/static/mission-console.html`
(241 lines), `backend/static/mission-console.js` (141 lines), styles in
`backend/static/style.css`. Target app: `frontend/` — no mission-console
composite or replay-sessions widget exists yet; present widgets are
`AIChatWidget.tsx`, `MapWidgetPanel.tsx`, `ClockWidget`, `DriveControlsWidget`,
`NotesWidget`, `TelemetryWidget`, `VideoWidget`.

**This page is mostly a composite re-mount, not new widgets.** The bottom region
is the *same* AI chat shell as `ai.html` — identical element IDs
(`#ai-session-list`, `#ai-message-form`, `#ai-provider-select`, …), driven by the
*same* `ai.js`. The map region is the *same* `MapWidget`. Only the **replay
sessions sidebar** (top-left) is unique to this page and owned by
`mission-console.js`. So:

- AI chat shell rows → **see [`ai.md`](ai.md)** (`ai.*`); this file records only the
  mission-console **deltas** (different kicker text, default run-mode, placeholder).
- Map area rows → **see [`map.md`](map.md)** (Pass A pending).
- Replay sidebar rows → inventoried **in full** below (`mc.replay.*`).

`planned?` / `implemented?` pre-filled. `target` and `decision` are intentionally
blank — filled in **Pass B (INV-B)**.

**Pre-fill key.** `planned?`: the new design doc
([operator-console.md](../design/operator-console.md)) widget table lists
**Replay Sessions** (line 84, "singleton; per-map track visibility is a Map
toggle"), **AI Session List** (line 83, "isolatable but low value"), and **Replay
Playback Controls** (line 85) as planned singleton widgets, and the data layer
already names `/api/replay/*` (line 27). `roadmap.md` makes **"Mission Console
flagship first"** the parity sequence (lines 48–49) and tracks the rebuild as
INV-A/B/C (lines 124–125). So replay-sidebar items read **yes (planned widget,
operator-console.md §widget-table)**; selection→drive wiring reads **unsure**
because the old page never wired it (see note). `implemented?`: searched
`frontend/src/` for `replay`/`mission-console`/`/api/replay`/`rollover`/
`telemetry_count` — **zero hits**; no replay-sessions widget and no composite page
exist, so the unique rows are **no**. Reused chat/map rows inherit `ai.md` /
`map.md` status.

## 1. Decision table

### Page shell & layout

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `mc` | node | panel | — | Page root `main.app-shell.mission-console-shell[data-page="mission-console"]`; stacks: `mission-console-grid` (replay sidebar + map) → map-height-resizer → `ai-chat-shell` (reused) → status bar | yes (Mission Console flagship, roadmap:48) | no | `workspace` | Drop | New app is a dockview workspace composing the same widgets; no fixed stacked page |
| `mc.intro` | leaf | panel | — | `<section data-page-intro>` left **empty**; `ai.js` `initAi()` skips intro injection when `data-page="mission-console"` | no | no | — | Drop | |
| `mc.grid` | node | panel | "Mission console workspace" | `section.mission-console-grid`; 2-col grid: replay sidebar + map area | yes | no | `workspace` | Drop | Layout artifact; dockview composes these panels |
| `mc.map-height-resizer` | leaf | separator | "Resize mission console map area" | `#ai-map-height-resizer`; pointer/arrow keys set map area height 320–1100px (shared resizer handler in `ai.js`) | no | no | — | Drop | Dockview handles panel sizing |
| `mc.status-bar` | node | panel | — | `#gcs-status-bar-container`; ES module mounts `StatusBar` from `map/ui/StatusBar.js`; exposed as `window.__gcsStatusBar` | unsure | partial: GCS status surface exists separately | `workspace` | Redesign | Tool-call status messages → workspace-level toast/notification surface; same call as ai.status-bar |

### Replay sessions sidebar (unique to this page — `mission-console.js`)

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `mc.replay` | node | panel | "Replay" / "Sessions" | `aside.panel.replay-sidebar.mission-console-replay-sidebar`; head / toolbar / list. **Read-only browser** — selecting a session only highlights it; it does **not** load replay or drive the map (see `mc.replay.list.item.select`) | yes (Replay Sessions widget, operator-console.md:84) | no | `ReplaySessionsWidget.tsx` | Rebuild | New singleton widget; superset is in replay.md (rp.side.*) — implement once, configure for context |
| `mc.replay.head.kicker` | leaf | label | "Replay" | static `.section-kicker` | no | no | `ReplaySessionsWidget.tsx` | Rebuild | Cascades from node |
| `mc.replay.head.title` | leaf | label | "Sessions" | static `<h2>` | no | no | `ReplaySessionsWidget.tsx` | Rebuild | |
| `mc.replay.head.count` | leaf | pill | "N session(s)" | `#mission-console-replay-count`; `render()` sets to `state.sessions.length` | yes (parity) | no | `ReplaySessionsWidget.tsx` | Rebuild | |
| `mc.replay.head.current` | leaf | pill | "No active session" / session id / error text | `#mission-console-replay-current`; shows `selectedSessionId \|\| currentSessionId`; also surfaces load/rollover error messages | yes (parity) | no | `ReplaySessionsWidget.tsx` | Rebuild | |
| `mc.replay.toolbar` | node | panel | "Replay session actions" | `div.session-toolbar[role=toolbar]` | yes (parity) | no | `ReplaySessionsWidget.tsx` | Rebuild | |
| `mc.replay.toolbar.refresh` | leaf | button(icon) | refresh — "Refresh sessions" | `#mission-console-refresh-replay`; `loadSessions()` → `GET /api/replay/sessions` → `{sessions, current_session_id}` | yes (parity) | no | `ReplaySessionsWidget.tsx` | Rebuild | |
| `mc.replay.toolbar.rollover` | leaf | button(icon "+") | plus — "Start new session" | `#mission-console-rollover-replay`; `rolloverSession()` → `POST /api/replay/sessions/rollover {reason:"mission_console_rollover"}` then reload | yes (parity) | no | `ReplaySessionsWidget.tsx` | Rebuild | |
| `mc.replay.list` | node | panel | — | `#mission-console-replay-list.session-list`; `render()` rebuilds; sorts by `started_at` desc | yes (parity) | no | `ReplaySessionsWidget.tsx` | Rebuild | |
| `mc.replay.list.empty` | leaf | label | "No replay sessions yet. Start the simulator/GCS and record telemetry." | shown when `sessions.length === 0` | unsure | no | `ReplaySessionsWidget.tsx` | Rebuild | |
| `mc.replay.list.item` | node | panel | — | `article.session-item`; gets `.active` when `session_id === selectedSessionId` | yes (parity) | no | `ReplaySessionsWidget.tsx` | Rebuild | |
| `mc.replay.list.item.select` | leaf | button | (session row) | `button.session-select`; click sets `selectedSessionId` + re-renders — **highlight only; no map/replay load wired** | unsure (old page never wired playback; new design splits Map track toggle + Playback Controls) | no | `ReplaySessionsWidget.tsx` | Rebuild | Session selection fires an event; Map track visibility and Playback Controls react independently per operator-console.md:84 |
| `mc.replay.list.item.title` | leaf | label | session start time | `strong.session-title`; `sessionLabel()` = `started_at` → "Mon DD, HH:MM" locale, else raw `session_id` | yes (parity) | no | `ReplaySessionsWidget.tsx` | Rebuild | |
| `mc.replay.list.item.stats` | node | panel | — | `span.session-meta`; three `.session-stat` chips (icon + count) | yes (parity) | no | `ReplaySessionsWidget.tsx` | Rebuild | |
| `mc.replay.list.item.stat.telemetry` | leaf | pill | telemetry frame count | `session.telemetry_count`; title "Telemetry frames" | yes (parity) | no | `ReplaySessionsWidget.tsx` | Rebuild | |
| `mc.replay.list.item.stat.controls` | leaf | pill | control count | `session.control_count`; title "Controls" | yes (parity) | no | `ReplaySessionsWidget.tsx` | Rebuild | |
| `mc.replay.list.item.stat.events` | leaf | pill | runtime event count | `session.runtime_event_count`; title "Events" | yes (parity) | no | `ReplaySessionsWidget.tsx` | Rebuild | |
| `mc.replay.list.item.id` | leaf | label | session id (truncated) | `span.session-id[title=id]`; HTML-escaped | unsure | no | — | Drop | Low-value internal ID; session title is sufficient |

### Reused AI chat shell (see `ai.md` `ai.*`) — mission-console deltas only

The whole shell (sessions sidebar, chat panel, provider strip, message list,
composer, slash menu, sources popover, resizers) is byte-identical element IDs to
`ai.html` and driven by `ai.js`. Inventory those rows in [`ai.md`](ai.md). Only
these page-level differences exist:

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `mc.chat` | node | panel | "Agent Chat" (kicker) | Same `section.panel.ai-chat-panel` as `ai.chat`; kicker reads **"Agent Chat"** vs ai.html's "General Chat" | see `ai.md` | partial (AIChatWidget) | `AIChatWidget.tsx` | Keep | Kicker text configurable via widget props |
| `mc.chat.run-mode-default` | leaf | (state) | Agent active by default | Run-mode toggle ships with **Agent** pre-selected (`.active`, `aria-pressed=true`) vs ai.html default; mission-console is agent-first | see `ai.md` (`ai.composer.run-mode.agent`) | no | `AIChatWidget.tsx` | Rebuild | Pass `defaultRunMode="agent"` prop when widget is in Mission Console context |
| `mc.chat.composer.placeholder` | leaf | (text) | "Ask the agent about missions, replay, map, settings, or rover state" | Textarea placeholder differs from ai.html's "Ask anything" | see `ai.md` (`ai.composer.input`) | no | `AIChatWidget.tsx` | Rebuild | Pass context-specific placeholder via widget prop |

### Reused map area (see `map.md`)

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `mc.map` | node | panel | — | `section#ai-map-area.mission-console-map-area` hosts `MapWidget` (`map/index.js`) mounted with `{sessionId, statusBar, missionListPosition:'right'}`; follows `ai:session-open` / `ai:session-refreshed` to (re)bind per **AI** session — note it tracks the AI session id, **not** the selected replay session | yes (Map widget planned) | partial (MapWidgetPanel exists) | `MapWidgetPanel.tsx` | Embed | Pass `missionListPosition:'right'` + `sessionId` + `statusBar` sink opts; wiring gap, not re-code |

### Cross-cutting behaviors

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `mc.behavior.timezone-header` | leaf | (behavior) | — | `mission-console.js` `fetchJson` adds `X-Operator-Timezone` (resolved tz) to every replay request | no | no | `data/runtimeStore.ts` | Rebuild | Add tz header to all GCS fetch calls in the data layer; cross-cutting |
| `mc.behavior.replay-map-decoupled` | node | (behavior) | — | Replay session selection and the Map's session binding are **independent** — the sidebar never tells the map which replay to render. New design must decide whether parity means wiring this or keeping it split (Map track toggle + Playback Controls widgets) | unsure | no | `workspace` | Redesign | Keep decoupled per operator-console.md:84; session selection fires an event, Map toggles replay track visibility independently via its own layer controls |

## 2. Style appendix (lossless backstop)

Values keyed by `id`; `@ style.css:<line>` is the authoritative source. Node rows
carry layout; leaf rows carry appearance. The chat-shell tokens live in `ai.md`;
only mission-console + replay-sidebar classes are below.

### Layout (nodes)

- `mc.shell` — `.mission-console-shell` `width:min(1600px, calc(100vw - 32px))`. `@ style.css:4393`
- `mc.grid` — `.mission-console-grid` grid `minmax(260px,320px) minmax(0,1fr)`; `gap:12px`; `align-items:stretch`; mobile collapses to 1col `@ style.css:6122`. `@ style.css:4397`
- `mc.replay` — `.replay-sidebar` `grid-area:sidebar`; flex column; `gap:12px`; `height:100%`; `overflow:hidden`; `padding:12px 6px 12px 12px`; `border:1px color-mix(--line 64%)`; `border-radius:var(--replay-card-radius)`; `background:color-mix(--panel 88%,--panel-strong)`; `box-shadow:var(--replay-card-shadow)`. Mission-console override adds `border-radius:18px` + `border-right` + stacked box-shadow `@ style.css:4404`. `@ style.css:1600`
- `mc.replay.head` — `.replay-sidebar .panel-head` grid 1col; `gap:10px`; `margin-bottom:0`. `@ style.css:1619`
- `mc.replay.toolbar` — `.session-toolbar` flex; `align-items:center`; `justify-content:flex-end`; `gap:8px`; `padding:0 6px 0 0`. `@ style.css:1863`
- `mc.replay.list` — `.replay-sidebar .session-list` `flex:1 1 auto`; `min-height:0`; `gap:8px`; `overflow-y:auto`; `padding:0 4px 4px 0`; `scrollbar-gutter:stable`; `overscroll-behavior:contain`. `@ style.css:1871`
- `mc.replay.list.item` — `.session-item` grid `minmax(0,1fr) 30px`; `gap:8px`; `align-items:center`; `padding:10px`; `border-radius:10px`; `background:color-mix(--panel-strong 54%)`; `border:1px color-mix(--line 52%)`; transitions. `.active`→accent border + `color-mix(--accent-soft 34%,--panel-strong)` `@ style.css:2051`; hover raises accent `@ style.css:2056`. `@ style.css:2038`
- `mc.replay.list.item.stats` — `.session-meta` flex-wrap; `gap:8px`; `align-items:center`. `@ style.css:2111`
- `mc.map` — `.mission-console-map-area` `margin-top:0`; `min-height:560px`. `@ style.css:4412`
- `mc.chat` (shell) — `.mission-console-chat-shell` `margin-top:12px`; `--ai-shell-height:560px`; `.ai-chat-panel{min-height:0}`. Base grid in `ai.md` `ai.chat-shell`. `@ style.css:4417`

### Appearance (leaves)

- `mc.replay.head.{count,current}` — `.session-head-meta .pill` `padding:4px 10px`; `background:color-mix(--panel-strong 92%)`; `border:1px color-mix(--line 42%)`; inset top highlight. Container `.session-head-meta` inline-flex wrap `gap:10px` `@ style.css:1840`. `@ style.css:1850`
- `mc.replay.toolbar.{refresh,rollover}` — `.replay-session-icon-btn` 34×34; `border-radius:10px`; svg 16px `fill:currentColor`; `background:color-mix(--panel-strong 72%)`; `border:1px color-mix(--line 74%)`; hover→accent. `:last-child` (rollover) `color:var(--accent)` + accent-gradient hover. CSS `::after` tooltip from `data-tooltip` (right-aligned, `font-size:.68rem`). `@ style.css:1762`
- `mc.replay.list.item.select` — `.session-select` `width:100%`; `text-align:left`; grid `gap:4px`; `justify-items:start`; transparent button (no border/shadow); hover is inert (`transform:none`). `@ style.css:2061`
- `mc.replay.list.item.title` — `.session-title` `display:block`; `font-size:.95rem`; `font-weight:650`; `line-height:1.2`. `@ style.css:2103`
- `mc.replay.list.item.stat.*` — `.session-stat` inline-flex; `gap:5px`; `padding:2px 6px`; `border-radius:999px`; `background:color-mix(--panel-strong 70%)`; `border:1px color-mix(--line 68%)`; svg 12px `opacity:.9`. `.session-item.active .session-stat`→accent border+bg `@ style.css:2136`. `@ style.css:2118`
- `mc.replay.list.item.id` — `.session-id` ellipsis; `white-space:nowrap`; `overflow:hidden`. Shared muted text `.session-select span` `color:var(--muted)`; `font-size:.72rem` `@ style.css:2141`. `@ style.css:2148`

### Dead CSS in `static/` not used by this page

`.session-delete` (@2086), `.session-sort-control` (@1640), `.record-tabs` (@2155)
are styled but **not rendered** by `mission-console.js` (no delete/sort/tabs here).
They belong to the richer `replay.html` sidebar — verify ownership in `replay.md`.

### Theme tokens (resolve in `style.css` `:root`/`[data-theme]`)

`--accent`, `--accent-soft`, `--line`, `--muted`, `--text`, `--panel`,
`--panel-strong`, `--bg-base`, `--replay-card-radius`, `--replay-card-shadow`,
`--ai-shell-height`. Chat/map tokens are listed in `ai.md` / `map.md`.
