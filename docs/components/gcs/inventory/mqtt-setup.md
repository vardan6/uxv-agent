# MQTT Setup page inventory — `static/mqtt-setup.html` + `static/mqtt-setup.js`

Pass A extraction (mechanical). Source: `gcs_server/static/mqtt-setup.html` (82 lines),
`gcs_server/static/mqtt-setup.js` (143 lines), styles in `gcs_server/static/style.css`.
Target app: `frontend/` — served at `/setup/mqtt` (`data-page="settings"`).

**This is the MQTT broker/topic configuration form.** One panel: a `form-grid` of
9 labeled inputs (8 text/number + 1 select for simulator backend) with Save and Reload
actions, a live broker-status pill in the panel header, and a dynamic status banner below
the form. On load, `GET /api/mqtt-config` populates the fields and `GET /api/snapshot`
provides the broker connection state and current simulator backend. On save, two sequential
POSTs fire (`/api/mqtt-config` then `/api/simulation-config`), the form re-fills from the
response, and `loadSetup()` re-runs 800 ms later to verify the reconnected broker state.

Per operator-console.md:134–137 the page **folds into Settings → Connectivity**. It is
currently duplicated as both this standalone page and a tab inside `settings.html`; the
new Settings rebuild consolidates them. A lightweight first-run gate is retained only if
the onboarding-gate open question is resolved as "yes" (see activeContext.md open
questions).

Common shell (sticky header, app-nav, page-intro) is injected by `common.js initShell()`
and is **inventoried once in `dashboard.md`** — not repeated here. The page-intro for
this page: title "MQTT Setup", subtitle "Update broker and topic values used by GCS
runtime and the simulator integration."

`planned?` / `implemented?` pre-filled. `target` and `decision` are intentionally
blank — filled in **Pass B (INV-B)**.

**Pre-fill key.** `planned?`: operator-console.md:134–137 says mqtt-setup folds into
Settings → Connectivity — all MQTT fields read **yes**. Broker pill reads **yes**
(broker status store exists in ADR 0031). Simulator backend select is absent from the
Connectivity spec but the VS-Code Settings rebuild covers all config-JSON fields, so
reads **unsure: not listed explicitly in Connectivity spec; implied by full-settings
rebuild scope**. Inline nav links read **no** (new app has no page-nav links). `implemented?`:
searched `frontend/src/` — no Settings widget or MQTT config form exists; broker status
is **partial** (TelemetryWidget.tsx:30 renders `broker.status` as plain text, no
pill-with-states in a settings context); all form fields are **no**.

**Pass B resolution — `/setup/mqtt` merge-vs-keep: MERGE (Drop standalone page).**
Content is 100% duplicated by `st.conn.*` in `settings.md`. There is no distinct
onboarding-gate behavior that warrants a separate route: users can reach Settings →
Connectivity from the workspace at any time. All form fields below are marked **Drop**;
Rebuild is tracked in `settings.md` under `st.conn.*`.

## 1. Decision table

### Page shell & layout

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `ms` | node | panel | — | Page root `body[data-page="settings"]` → `main.app-shell[data-app-shell]`; common shell injected by `initShell({ page:'settings', title:'MQTT Setup', subtitle:'…' })`; stacks `data-page-intro` → `section.inline-actions` → `section.page-grid` (1 article) | yes (operator-console.md:134–137, folds into Settings → Connectivity) | no | `SettingsWidget.tsx` | Drop | Standalone `/setup/mqtt` route dropped; content folds into Settings → Connectivity; resolution = merge |

### Inline nav links

Unique to this page — three quick-jump anchor links placed above the panel, outside the
common app-nav.

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `ms.nav` | node | panel | — | `section.inline-actions`; flex row of 3 nav-link anchors | no (new app has no page-level nav links) | no | — | Drop | Page nav replaced by workspace navigation |
| `ms.nav.settings` | leaf | link | "Settings" | `a.nav-link[href="/settings"]`; jump to settings page | no | no | — | Drop | |
| `ms.nav.replay` | leaf | link | "Replay" | `a.nav-link[href="/replay"]`; jump to replay page | no | no | — | Drop | |
| `ms.nav.dashboard` | leaf | link | "Back to Dashboard" | `a.nav-link.nav-link-accent[href="/"]`; accented (primary-gradient) | no | no | — | Drop | |

### MQTT Settings panel

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `ms.panel` | node | panel | — | `article.panel`; single panel in `section.page-grid`; radius 20 px, padding 18 px | yes | no | `SettingsWidget.tsx` | Drop | Panel structure drops; all content rows fold into `st.conn.*` in settings.md |
| `ms.panel.head` | node | panel | — | `div.panel-head`; flex row, space-between, gap 16 px; title left, broker pill right | yes | no | — | Drop | Cascades from parent |
| `ms.panel.head.title` | leaf | label | "3D Env MQTT Settings" | `h2`; static; `margin-top:4px` | yes | no | — | Drop | Becomes Settings category heading |
| `ms.panel.head.broker-pill` | leaf | pill | "Loading" / "Connected" / "Connected, waiting for data" / "Connected, stale data" / "Connected, partial data" / "disconnected" / error text | `span#setup-broker-pill.pill`; class toggled to `.ok`/`.warn`/`.danger`; driven by `brokerBadgeState(snapshot.broker)` on load and after save; initial state `warn` "Loading" | yes (broker state in runtime store, ADR 0031) | partial (`TelemetryWidget.tsx:30` shows `broker.status` as plain text; no pill-in-settings context) | `SettingsWidget.tsx` | Drop | Rebuilt via `st.conn.pill` in settings.md; Drop standalone instance |
| `ms.panel.hint` | leaf | label | "Saved to `<path>`. After save, the GCS reconnects using these values immediately." | `p.hint`; color `var(--muted)`; `code#settings-path` filled from `config.settings_path` returned by `GET /api/mqtt-config` | yes | no | `SettingsWidget.tsx` | Drop | Carried by `st.conn.hint` in settings.md |
| `ms.panel.form` | node | panel | — | `form#mqtt-form.form-grid`; 2-col grid, gap `0 18px`, margin-top 20 px; `submit` → `saveSetup()` | yes | no | `SettingsWidget.tsx` | Drop | Duplicate of `st.conn.form` in settings.md |
| `ms.panel.form.broker-host` | leaf | input | "Broker Host" / placeholder "192.0.2.10" | `input#broker-host[type=text][required]`; maps to `mqtt.broker_host`; populated by `GET /api/mqtt-config`, posted to `POST /api/mqtt-config` | yes | no | `SettingsWidget.tsx` | Drop | Duplicate of `st.conn.broker-host`; Rebuild tracked in settings.md |
| `ms.panel.form.broker-port` | leaf | input | "Broker Port" | `input#broker-port[type=number][min=1][step=1][required]`; maps to `mqtt.broker_port`; default 1883 on load | yes | no | `SettingsWidget.tsx` | Drop | Duplicate of `st.conn.broker-port` |
| `ms.panel.form.topic-prefix` | leaf | input | "Topic Prefix" / placeholder "/projects/remote-rover" | `input#topic-prefix[type=text]`; maps to `mqtt.topic_prefix`; optional | yes | no | `SettingsWidget.tsx` | Drop | Duplicate of `st.conn.topic-prefix` |
| `ms.panel.form.client-id` | leaf | input | "Client ID" / placeholder "gcs-web" | `input#client-id-input[type=text]`; maps to `mqtt.client_id`; optional | yes | no | `SettingsWidget.tsx` | Drop | Duplicate of `st.conn.client-id` |
| `ms.panel.form.control-topic` | leaf | input | "Control Topic" / placeholder "control/manual" | `input#control-topic[type=text][required]`; maps to `mqtt.control_topic` | yes | no | `SettingsWidget.tsx` | Drop | Duplicate of `st.conn.control-topic` |
| `ms.panel.form.state-topic` | leaf | input | "Telemetry Topic" / placeholder "telemetry/state" | `input#state-topic[type=text][required]`; maps to `mqtt.state_topic` | yes | no | `SettingsWidget.tsx` | Drop | Duplicate of `st.conn.state-topic` |
| `ms.panel.form.camera-topic` | leaf | input | "Camera Topic" / placeholder "camera-feed" | `input#camera-topic[type=text][required]`; maps to `mqtt.camera_topic` | yes | no | `SettingsWidget.tsx` | Drop | Duplicate of `st.conn.camera-topic` |
| `ms.panel.form.control-hz` | leaf | input | "Control Rate (Hz)" | `input#control-hz[type=number][min=1][step=1][required]`; maps to `mqtt.control_hz`; default 20 on load | yes | no | `SettingsWidget.tsx` | Drop | Duplicate of `st.conn.control-hz` |
| `ms.panel.form.simulation-backend` | leaf | select | "Active Simulator Backend"; option "3d-env" | `select#simulation-backend-select`; maps to `simulation.backend`; loaded from `GET /api/snapshot`; saved via separate `POST /api/simulation-config { simulation: { backend } }` | unsure: not listed explicitly in Connectivity spec; implied by full-settings rebuild scope | no | `SettingsWidget.tsx` | Drop | Duplicate of `st.conn.sim-backend`; include in Connectivity rebuild |
| `ms.panel.form.actions` | node | panel | — | `div.form-actions`; `grid-column:1/-1`; flex row, gap 12 px, margin-top 8 px | yes | no | — | Drop | Cascades |
| `ms.panel.form.actions.save` | leaf | button | "Save MQTT Settings" | `button[type=submit]`; triggers `saveSetup()`: status → "Saving…", pill → warn "connecting", POST `/api/mqtt-config` then POST `/api/simulation-config`, re-fills form, schedules `loadSetup()` after 800 ms | yes | no | `SettingsWidget.tsx` | Drop | See `st.conn.save` in settings.md |
| `ms.panel.form.actions.reload` | leaf | button | "Reload" | `button#reload-config.ghost[type=button]`; calls `loadSetup()` on click: GET `/api/mqtt-config` + GET `/api/snapshot` in parallel, fills form + pill + path | yes | no | `SettingsWidget.tsx` | Drop | See `st.conn.reload` in settings.md |
| `ms.panel.status` | leaf | label | "Loading shared MQTT settings." / "Saving shared config…" / "Current broker target: `host:port`." / "Saved. GCS is reconnecting to `host:port`." / error text | `p#setup-status.status-banner`; color `var(--muted)`; updated by `setSetupStatus()` on every async transition; error text replaces on failure | yes | no | `SettingsWidget.tsx` | Drop | See `st.conn.status` in settings.md |

### API / WS surface

| Endpoint | Method | Called by | Payload / Response fields used |
|----------|--------|-----------|-------------------------------|
| `/api/mqtt-config` | GET | `loadSetup()` on page-load, Reload click, and after save delay | `{ mqtt: { broker_host, broker_port, topic_prefix, client_id, control_topic, state_topic, camera_topic, control_hz }, settings_path }` |
| `/api/mqtt-config` | POST | `saveSetup()` on form submit | Body: `{ mqtt: { … } }`; response: same shape as GET; re-fills form + path |
| `/api/snapshot` | GET | `loadSetup()` (parallel with mqtt-config) | `{ broker: { connected, status, last_telemetry_ts, last_camera_ts, telemetry_stale, camera_stale }, simulation: { backend } }` |
| `/api/simulation-config` | POST | `saveSetup()` after mqtt-config POST | Body: `{ simulation: { backend } }`; response not read by UI |

## 2. Style appendix

### Layout — nodes

| id | layout | source |
|----|--------|--------|
| `ms` | `.app-shell`: `width:min(1440px,calc(100vw-32px))`, `margin:0 auto`, `padding:18px 0 40px`; `body[data-page="settings"]` uses same shell as settings page | `style.css:289–293` |
| `ms.nav` | `.inline-actions`: `display:flex`, `gap:10px`, `flex-wrap:wrap` | `style.css:627–631` |
| `ms.panel` | `.panel`: `border-radius:20px`, `padding:18px`; inherits panel bg/border/shadow/backdrop from `.panel` rule | `style.css:532–535`, `style.css:296–302` |
| `ms.panel.head` | `.panel-head`: `display:flex`, `justify-content:space-between`, `align-items:flex-start`, `gap:16px`, `margin-bottom:16px` | `style.css:541–547` |
| `ms.panel.form` | `.form-grid`: `display:grid`, `grid-template-columns:repeat(2,minmax(0,1fr))`, `gap:0 18px`, `margin-top:20px`; each `label` is an implicit grid cell | `style.css:2677–2682` |
| `ms.panel.form.actions` | `.form-actions`: `grid-column:1/-1`, `display:flex`, `gap:12px`, `margin-top:8px`, `flex-wrap:wrap` | `style.css:2684–2690` |

### Appearance — leaves

| id | appearance | source |
|----|------------|--------|
| `ms.nav.settings` | `.nav-link`: `padding:11px 16px`, `border-radius:14px`, `border:1px solid var(--line)`, `background:var(--button-secondary-gradient)`, `color:var(--text)`, `text-decoration:none`; hover: `translateY(-1px)`, brighter border; focus-visible: accent ring | `style.css:372–385`, `style.css:606–624` |
| `ms.nav.replay` | same as `ms.nav.settings` | `style.css:372–385` |
| `ms.nav.dashboard` | `.nav-link-accent` extends `.nav-link`: `background:var(--button-active-gradient)`, `border-color:color-mix(in srgb,var(--accent) 45%,var(--line))` | `style.css:382–385` |
| `ms.panel.head.title` | `.panel-head h2`: `margin-top:4px`; inherits body heading size | `style.css:549–551` |
| `ms.panel.head.broker-pill` | `.pill`: `padding:6px 10px`, `border-radius:999px`, `font-size:0.85rem`, `white-space:nowrap`; `.pill.ok`: `color:var(--accent-strong)`, `bg:var(--ok-bg)`; `.pill.warn`: `color:var(--warn)`, `bg:var(--warn-bg)`; `.pill.danger`: `color:var(--danger)`, `bg:var(--danger-bg)` | `style.css:553–574` |
| `ms.panel.hint` | `.hint`: `color:var(--muted)`, `margin-top:16px`, `line-height:1.45` | `style.css:709–715` |
| `ms.panel.form.broker-host` … `ms.panel.form.control-hz` (all text/number inputs) | `input`: `padding:11px 12px`, `background:var(--panel-strong)`, `color:var(--text)`, `border-radius:14px`, `border:1px solid var(--line)`, `font:inherit`; hover: `translateY(-1px)`, brighter border; focus-visible: accent glow | `style.css:2257–2264`, `style.css:577–583`, `style.css:606–624` |
| `ms.panel.form.simulation-backend` | `select`: same padding/bg/radius/border as inputs; options: `bg:var(--panel-strong)`, `color:var(--text)` | `style.css:2257–2269` |
| `ms.panel.form.actions.save` | `button` (primary): `background:var(--button-primary-gradient)`, `color:var(--text)`, `display:inline-flex`, `align-items:center`; hover/focus-visible shared with inputs | `style.css:585–624` |
| `ms.panel.form.actions.reload` | `button.ghost`: `background:var(--button-secondary-gradient)`; otherwise same as primary button | `style.css:599–624` |
| `ms.panel.status` | `.status-banner`: `color:var(--muted)`, `margin-top:16px`, `line-height:1.45` | `style.css:709–715` |
