# GCS — Requirements

What the Ground Control Station must provide from the operator's point of view. The product-level source of truth for the operator workflow, page behavior, safety invariants, and acceptance criteria.

Companion documents:

- [design.md](./design.md) — implementation strategy, runtime seams, file layout, current limitations.
- [design.md](./design.md) — HTTP/WebSocket surface, control model, settings model.

If documents disagree:

- this document wins for product intent and operator-visible behavior
- `design.md` wins for implementation details

## Pages At A Glance

The Ground Control Station serves five browser pages:

| Page | URL | Purpose |
|---|---|---|
| Dashboard | `/` | Live rover control, telemetry, and video |
| Replay | `/replay` | Inspect recorded sessions |
| Settings | `/settings` | Configure connectivity, video, LLMs, and import/export |
| MQTT Setup | `/setup/mqtt` | Edit and reconnect the broker connection |
| AI Agent | `/ai` | Chat / Agent today; converging toward a single primary Agent experience |

The AI page is documented separately in the [AI Agent component](../ai-agent/requirements.md).

## Dashboard (`/`)

The dashboard is the primary operator surface. It is split into a telemetry/state area and a live camera area, with a compact header for status and navigation.

### What The Operator Sees

- **Camera feed**: a live JPEG stream of the rover's POV camera, delivered through the MQTT → WebSocket bootstrap path. A status indicator shows whether the feed is fresh.
- **Telemetry panel**: rover speed, heading, deterministic virtual GPS position, current camera mode (POV / follow), power readings, and freshness state.
- **Controller status**: an indicator showing whether *this* browser holds the controller lock or whether someone else does.
- **Broker status**: connection state to the MQTT broker, including last activity time.
- **Take Control / Release**: buttons to acquire or release the controller lock.
- **On-screen control overlay**: visual representation of the keyboard bindings for users who want to see what keys do what.

### Taking And Releasing Control

Only one browser can drive the rover at a time. Control is **focus-driven**: the focused, visible dashboard browser is the active controller. The operator does not need to manually arbitrate — switching tabs or losing focus releases control immediately, and the GCS publishes neutral controls so motion cannot stick.

The operator should expect:

- pressing keyboard movement keys only sends commands when the dashboard tab is focused and visible
- losing focus immediately stops the rover (does not coast)
- a control timeout never auto-releases — only focus/visibility changes or a real disconnect deactivates control
- regaining focus restores control without any explicit reclaim

### Keyboard Controls

Bindings come from shared config (`key_bindings`). The default arrow-key and `W A S D` mapping is a fallback only. Operators can override bindings in the shared config file; the dashboard reads them at load.

### What "Working" Looks Like

When everything is connected:

- the camera feed shows a live image with recent timestamps
- telemetry values change as the rover moves
- the broker indicator is green
- pressing movement keys produces visible motion
- releasing keys returns the rover to neutral

When something is wrong, the operator sees stale-data indicators, a red broker status, or a "no telemetry" notice. The simulator may stop publishing entirely if no GCS presence is detected (see *Bandwidth-Aware Publishing* below).

### Bandwidth-Aware Publishing

In `auto` telemetry policy, the simulator only publishes telemetry and camera frames when at least one GCS instance has a fresh presence record. From the operator's view, this means:

- starting the GCS makes the simulator start publishing
- stopping the GCS (or all browsers disconnecting) makes the simulator stop
- this saves bandwidth in data-sensitive environments

The simulator can also be manually forced to `force_on` or `force_off` from its own settings.

## Replay (`/replay`)

The replay page lets the operator inspect previously recorded sessions.

### What The Operator Sees

- **Session list**: each recorded session with start time, duration, event counts, and brief metadata
- **Timeline**: a scrubbable timeline of telemetry, control, and runtime events for the loaded session
- **Map view**: a Leaflet-based first-generation map showing the rover's recorded path, scene-map objects, and event markers
- **Event details**: structured display of telemetry, control inputs, and runtime events at the current time

### What The Operator Can Do

- load a session and play back its timeline
- scrub to any point and see the rover's state at that moment
- inspect the recorded path on the map
- delete sessions
- manually roll over the active session (start a fresh recording boundary)

### What Is Not Available Yet

- synchronized recorded video playback alongside telemetry
- live map view on the main dashboard (only replay has a map)
- multi-session comparison in the UI (the AI Agent has tools for this)

## Settings (`/settings`)

The settings page is organized as tabs. Each tab covers a distinct configuration area.

### Connectivity Tab

Edit MQTT broker host, port, topic prefix, and topic names. Saving applies live — the GCS reconnects without restart. The same surface is available standalone at [MQTT Setup](#mqtt-setup-setupmqtt) for first-run onboarding.

### Video Tab

Choose video mode flags. Changes are persisted and broadcast to all connected browsers.

### Appearance Tab

Theme and display settings for the dashboard.

### Add LLM Provider Tab

Manage the LLM provider records used by AI Chat and the future rover-agent layer.

The operator can:

- add a new provider with a display name, type (OpenAI / OpenAI-compatible / Ollama / Anthropic / Google Gemini / Mistral / NVIDIA NIM / OpenRouter / LM Studio / Custom HTTP), base URL, model name, optional embedding model, secret reference, and notes
- edit any existing provider
- enable or disable a provider without deleting it
- delete a provider
- run a quick test that sends a small probe to verify the provider responds

The model routing section assigns providers to AI purposes:

- General Chat
- Rover Intent Parser
- Mission Planner
- Reporter
- Embeddings
- Vision / Object Description

Each purpose has a primary and an optional fallback. These assignments persist in the loaded GCS settings JSON.

### JSON Tab

Export and import selected settings sections. The operator chooses which sections to include via checkboxes:

- connectivity
- video
- appearance
- LLM providers
- model routing

Important behavior:

- **export does not include raw API keys** — only secret reference names
- **missing sections in an imported file are preserved** — older JSON files do not erase newer settings
- **import previews changes before applying** — operator confirms before settings change

## MQTT Setup (`/setup/mqtt`)

A standalone first-run page for editing MQTT settings. Equivalent to the Connectivity tab in Settings but accessible without the full settings UI. Useful when initial connectivity is broken and the dashboard cannot load fully.

## AI Agent (`/ai`)

For the full AI agent product requirements — intent parsing, planning shell, mission execution, memory, and operator interaction model — see [AI Agent requirements](../ai-agent/requirements.md). This section covers the GCS-owned surfaces on the `/ai` page: the map widget, mission list, and edit UI.

### Map widget

The `/ai` page hosts a reusable `MapWidget` (Leaflet + `L.CRS.Simple`, local scene metres) that renders the rover's operating scene and mission overlays. The durable operator-facing entity is the flat **Mission** from ADR 0021: one sidebar row = one Mission, with stable `#index`, editable name, `origin`, and `origin_chat_id`. The map is vehicle-aware — it reads the active `VehicleProfile` to populate property panels and enforce vehicle-specific dispatch rules.

The map widget must:

- render the terrain scene (scene objects, road graph, blockages, corridors) at all times
- display a `MissionListPanel` showing one row per Mission, with the independent **Visible / Selected / Active** states defined by ADR 0021
- render mission overlays for AI-created and operator-created Missions as distinct visual layers; per-waypoint provenance styling is no longer a load-bearing requirement for the flat Mission model
- track and display the live vehicle position via the `/ws` telemetry stream (polling fallback at 2 s)
- support a `SelectionPanel` that shows waypoint-level details for any selected waypoint
- support a context menu (right-click or long-press) for point-level actions (insert waypoint before/after, delete, set as home)
- display hint toasts for gestures and a keyboard help overlay

### Mission CRUD

The map widget is the primary mission authoring surface on `/ai`. No separate Missions page exists.

Operators must be able to:

- **Create a mission from scratch** using `➕ New mission` — lay down waypoints manually on the map
- **Review AI-created missions** — the agent emits a new Mission row; the map renders it immediately
- **Edit missions** — drag waypoints, add/delete waypoints, reorder
- **Execute mission** — hand the Mission to the controller via the row's `▶` button (Strict) or via AI tool calls per the active execution mode (Confirm / Autonomous)
- **Export plan** — export a Mission as a `.plan` file without executing when export is surfaced in the UI

Per [ADR 0022](../../cross-cutting/decisions/0022-drop-operator-approval-gate.md), Missions no longer carry an operator-facing approval state. Every Mission row is immediately playable; the safety gate lives in the execution mode (Strict / Confirm / Autonomous) and the executing-mission edit lock, not in a per-Mission approval flag.

### Mission editing UX

These rules describe operator-visible behaviour. Specific UI choices below are
the current intent from the 2026-05-28 grilling cycle and may be adjusted
after live UI review.

- **Editing a locked mission** — when the operator presses edit on a mission
  whose status is in the locked set (`approved`, `exported`, `cutover_pending`,
  `executing`), the widget asks for explicit confirmation
  ("This mission is locked. Create an editable copy?") before forking. Once
  the fork is created, the original mission is hidden from the map for the
  duration of the edit so its waypoints do not appear underneath the fork.
  Exiting edit restores the original to the visible set.
- **Edit-mode indication** — the row whose mission is being edited carries a
  visible state indicator (currently a left-edge amber stripe + the row's
  pencil icon swapped to a "done" glyph). The edit banner exposes a "Done"
  button (auto-save is on; "Done" reads better than "Exit"). The pencil icon
  on the row also toggles edit on/off. The state indicator never reuses a
  mission's identity colour.

### Row click and selection

- **Full-row click target** — clicking anywhere on a sidebar row activates
  that mission. Inner controls (visibility, edit, colour, kebab) do not
  activate the row.
- **Multi-selection keys** — plain click sets selection to just this row;
  shift-click extends the selection from the last plain-clicked row to the
  clicked row in the current sort order; cmd/ctrl-click toggles a row in or
  out of the selection. Active mission after multi-select = the last-clicked
  row; active is always inside the selection.
- **Map ↔ sidebar sync** — clicking a mission's polyline or any of its
  waypoints on the map performs the same activation/selection as the
  corresponding row click, with the same modifier keys.
- **Empty area** — clicking empty sidebar space or empty map area does not
  clear the selection.
- **Bulk action bar** — the existing `BulkEditActionBar` becomes visible when
  two or more missions are selected. Single-mission actions stay in the row
  kebab.

### Map view controls

The widget exposes a floating toolbar (top-right of the map):

- **Fit to scene** — pans/zooms so the full scene bounds fill the viewport.
- **Fit to selection** (keyboard `f`) — fits to the bounding box of the
  current selection, or the active mission when no multi-selection is in
  play.
- **Map style** — switches between terrain (default), scene image, and a
  plain grid background. The chosen style is remembered locally per browser.

The map is clamped to scene bounds — the operator cannot pan past the scene
edges or zoom out further than "scene fills viewport." Fit-to-scene is the
return affordance.

### Per-mission colour

- Each mission has an identity colour, surfaced as a swatch in the sidebar
  row. The widget assigns one automatically from a curated palette; the
  operator can change it by opening the row's colour picker (palette swatches
  + a "Custom…" hex picker). A reset affordance restores the
  palette-assigned default.
- The mission colour is durable across reloads.
- Mission colour is independent of state indicators (edit-mode stripe,
  selection, active focus); state never overrides identity.

### Sorting

The sidebar exposes a sort dropdown. Available orderings:

- Updated date (newest first) — default
- Created date (newest first)
- Status
- Label A-Z
- Selected missions first, then by updated date
- Visible missions first, then by updated date

The choice is remembered locally per browser.

### Import / Export

The sidebar header offers an overflow menu containing Import, Export active,
Export selection, and Export all visible. Options that do not apply (e.g.
"Export selection" with nothing selected) are disabled.

- **Import** — accepts a JSON file containing a single mission object or an
  array of missions. Imported missions enter at the lowest writable status
  (currently `planning`); their incoming IDs and audit/timestamp fields are
  discarded server-side. Invalid input shows a toast; partial batches are not
  applied.
- **Export** — produces JSON containing only authored content (waypoints,
  labels, colour). Lifecycle and infrastructure fields (`id`, `status`,
  timestamps, `client_version`, audit fields) are stripped so that the
  exported file is a recipe, not a snapshot.
- KML / GPX / CSV are out of scope for now; the widget's coordinate frame is
  scene-local, not WGS84.

### Concurrency and edit-lock invariants

- All edits carry `client_version` for optimistic CAS. The backend rejects stale writes with `409 Conflict`.
- Manual edits mutate the Active Mission in place. AI-driven changes default to clone-and-edit, producing a new Mission row unless the operator explicitly requests an in-place AI edit.
- No mutation of an executing mission is permitted. The widget enforces this with short-circuit gesture handlers; the backend enforces it server-side.
- The widget consumes the flat Mission API directly; overlay payloads still emit `revision_id` as an alias of `mission_id` (cosmetic).

### Safety invariants

- Execution requires a separate explicit operator action in Strict, an operator confirmation banner in Confirm, or an AI tool call in Autonomous. Per [ADR 0022](../../cross-cutting/decisions/0022-drop-operator-approval-gate.md), there is no per-Mission approval gate in front of any of these.
- The edit lock during execution is not bypassable from the frontend.
- The map widget never issues low-level MQTT commands directly.

The Mission CRUD and Safety Invariants sections above describe **Strict mode** behaviour — the shipped default for real-rover builds. [ADR 0021](../../cross-cutting/decisions/0021-mission-lifecycle.md) supersedes [ADR 0002](../../cross-cutting/decisions/0002-two-approval-model.md) and [ADR 0012](../../cross-cutting/decisions/0012-map-widget-safety-invariants.md) and introduces two additional modes — **Confirm** (operator confirms an AI-armed execution via a banner) and **Autonomous** (sim-build default; AI may execute directly). Mode lives in `Settings → Mission Lifecycle`. Invariants 2–4 of ADR 0012 (no client-side mutation of executing missions, no silent overwrites, no inventing backend contracts) survive all modes. ADR 0021 also defines the **flat Mission sidebar** (one row = one Mission, with `#index`, editable name, `origin`, `origin_chat_id`) and the **Visible / Selected / Active** three-state UI. See ADR 0021 for the full lifecycle and tool surface.

## Cross-Cutting Behavior

### Freshness Indicators

Throughout the UI, indicators distinguish:

- **fresh**: data received recently, within the configured threshold
- **stale**: data older than the threshold but still present
- **absent**: no data available

The operator should treat stale telemetry as suspect — the rover may not actually be where the dashboard shows.

### Single-Operator Assumption

The current GCS is single-instance. Multi-browser use within one GCS works (focus determines who drives), but multi-GCS deployment is not fully defined yet.

### No Authentication Yet

Anyone who can reach the GCS URL can use it. There is no login, no role separation, and no audit log. This is acceptable for development and demos. Production use requires the work described in the roadmap.

## Acceptance Criteria

A new operator should be able to, without reading source:

1. open the dashboard, see telemetry, see live video, take control, drive the rover
2. switch to the replay page, find a previous session, play it back, inspect the path on the map
3. open settings, add an LLM provider, run a quick test, and assign it to General Chat
4. open the AI page, ask a question in Chat mode, see the assistant respond
5. switch the AI page to Agent mode, ask "what is in front of the rover?", and see tool calls and a deterministic answer

If any of these is hard to do without reading code, that is a UX bug worth filing.
