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

### Mission Lifecycle Tab

Controls how missions move from creation to execution. Settings:

- **FC adapter type** — `json_file` (local simulation, default) / `file_sink` (write uploads to `data/fc_sink/`) / `mavlink` (real FC via pymavlink) / `mavsdk` (real FC via MAVSDK)
- **Connection URL** — shown when adapter is `mavlink` or `mavsdk` (e.g. `udp:192.168.1.x:14550`)
- **Heartbeat timeout** and **Request timeout** — shown when adapter is `mavlink` or `mavsdk`
- **Execution mode** — Strict / Confirm / Autonomous (see ADR 0021 §1)
- **Confirm timeout** — 3–60 s (shown when mode is Confirm)
- **Auto-overlay new missions** — default on
- **Steal map focus** when active chat creates a mission — default on
- **Default name template** — default `"Untitled mission"`

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

### RAG Tab

Manage the embedding index used by the AI assistant to ground answers in project documentation.

The operator can:

- select the active embedding model from a dropdown listing every provider configured for the **Embeddings** routing purpose; changing the selection immediately updates the active model and refreshes the index status
- see the status of the selected model's index: **Up to date**, **Stale** (docs changed since last run), **Not indexed** (never built for this model), or **Model mismatch** (manifest dimension does not match current provider config)
- see the collection name, number of indexed chunks, and when the index was last updated
- run **Update Index** — re-embeds only documents that have changed since the last run; disabled when status is **Not indexed** or **Model mismatch**
- run **Rebuild Index** — deletes the current collection and re-embeds every document from scratch; always available; requires confirmation
- see an actionable error message when Qdrant is not running: *"Qdrant is not running. Start it with `bin/rag up`."*

Each embedding model retains its own index collection in Qdrant. Switching models does not destroy another model's collection; the operator can switch freely and each model's staleness is independently tracked.

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

### Chat workspace layout

The `/ai` page's conversation workspace must remain a light operator GUI, not a heavy admin console. The sessions sidebar and conversation panel should use a narrow, low-contrast resize divider consistent with the newer mission-map sidebar divider. The divider must remain easy to drag, keyboard-accessible, and hidden in the existing mobile stacked layout.

The sessions sidebar should stay compact enough that the conversation remains the primary workspace while still exposing active/archived filters, search, session actions, and readable session previews. Visual cleanup must not change chat/session persistence, provider selection, message sending, retry/stop behavior, source controls, or the map widget below the chat.

### Map widget

The `/ai` page hosts a reusable `MapWidget` (Leaflet + `L.CRS.Simple`, local scene metres) that renders the rover's operating scene and all mission overlays. The map is vehicle-aware — it reads the active `VehicleProfile` to populate property panels and enforce vehicle-specific dispatch rules.

The map widget must:

- render the terrain scene (scene objects, road graph, blockages, corridors) at all times
- display a `MissionListPanel` showing revisions grouped by operation, with status badges
- render mission overlays (AI-proposed and operator-authored) as distinct visual layers with provenance-aware per-waypoint styling (`ai` / `user` / `ai+edited`)
- track and display the live vehicle position via the `/ws` telemetry stream (polling fallback at 2 s)
- support a `SelectionPanel` that shows waypoint-level details and provenance for any selected waypoint
- support a context menu (right-click or long-press) for point-level actions (insert waypoint before/after, delete, set as home, detach from AI proposal)
- display hint toasts for gestures and a keyboard help overlay
- provide **layer visibility toggles** for the scene-mode layers: terrain heightmap, roads, scene objects, and grid — each independently show/hide-able from a toolbar within the map panel (parity with the replay page layer toolbar)
- provide **fit-bounds toolbar buttons**: fit to scene (full 3d-env extent), fit to focused mission, fit to visible-mission union — explicit buttons, not only auto-fit on focus change
- show a **cursor/info bar** at the bottom of the map panel: cursor position in scene metres, sampled ground elevation in scene `z`, WGS84 when a Mission origin exists, and current selection detail — parity with the replay page info bar plus mission-authoring terrain context
- provide a **view mode selector**: Virtual Terrain (heightmap gradient + objects), CAD/Object View (objects only, flat background), Heightmap (raw elevation colourmap), and Basemap (WGS84/OpenStreetMap) — view mode changes the map background/projection surface, not mission-list state or mission overlays
- provide a shared **map authoring toolbar** at the bottom of the map canvas, clear of top VIEW/NAV/fit controls and Leaflet zoom controls; it owns add-waypoint, corridor/survey pattern draw, geofence draw/save/clear, and sketch clear/generate actions instead of exposing those tools only inside Basemap mode
- surface, on each mission row: a status stripe + status label, the mission's vehicle/profile icon, a created-at date, an origin badge that distinguishes manual (👤), AI (🤖), and AI-then-operator-edited (✏️), an inline-renamable name (auto-numbered when untitled), and an edit ⇄ done toggle
- let a click anywhere on a mission row activate that mission (Active+Visible), with shift/meta/ctrl extending the multi-select
- offer **mission-management affordances** in the list: a per-mission colour override (colour picker with custom hex + reset), a persisted list **sort** (by updated / created / status / label / selection / visibility), and a `⋯` overflow menu carrying sort and **JSON import / export**

### Mission CRUD

The map widget is the primary mission authoring surface on `/ai`. No separate Missions page exists.

Operators must be able to:

- **Create a mission from scratch** using `➕ New mission` or the shared map authoring toolbar — lay down waypoints manually by clicking the active map view; corridor/survey pattern generation and geofence drawing are exposed from the same toolbar, not as controls that appear only after enabling Basemap
- **Review AI-proposed revisions** — the agent emits a revision; the map renders it immediately
- **Edit AI-proposed or operator-authored revisions** — drag waypoints, add/delete waypoints, reorder
- **Execute a mission** (▶) — uploads the mission to the FC and starts execution; available on any mission row with an active revision that is not already executing, paused, or completed
- **Pause a mission** (⏸) — holds the vehicle in place mid-mission (mode switch to HOLD on the FC); shown while mission is `executing`; toggles back to ▶ for resume
- **Resume a mission** (▶) — resumes without rewinding the mission when the active FC adapter has asserted the required firmware resume policy; shown while mission is `paused`
- **Stop a mission** (⏹) — holds the vehicle in place and marks mission `aborted`; shown while mission is `executing` or `paused`
- **Rename a mission** inline (double-click the name) and **Delete a mission** — singly, or in bulk from the selection batch bar; an executing mission is refused
- **Recolour a mission** via its colour chip, overriding the automatic palette colour
- **Import / export missions as JSON** via the list's `⋯` overflow menu — export serialises the visible/selected missions; import creates one flat Mission per entry

### Mission Row Button Layout

Every mission row has five fixed button slots. Inactive slots are hidden but hold space so columns align across all rows.

```
[ ✏️ edit ] [ ▶/⏸ play-pause ] [ ⏹ stop ] [ 🗑 delete ] [ 👁 visibility ]
```

| Row state | edit | play-pause | stop | delete | vis |
|---|---|---|---|---|---|
| idle | ✏️ | ▶ | — | 🗑 | 👁 |
| executing | — | ⏸ | ⏹ | 🗑 | 👁 |
| paused | — | ▶ | ⏹ | 🗑 | 👁 |
| completed / aborted | — | — | — | 🗑 | 👁 |

Icon-only buttons; no text labels. Hover tooltip (`title`) on each active slot.

### Mission Execution via AI Chat

When execution mode is **Autonomous** or **Confirm** (ADR 0021 §1), the AI can execute
directly from chat: "create a mission and run it" creates a mission in the sidebar and
starts it immediately (Autonomous) or shows a confirmation banner (Confirm). The mission
appears as `executing` in the sidebar with ⏸ and ⏹ buttons active.

The operator can pause or stop from chat ("pause the mission", "stop the mission") in
addition to using the sidebar buttons — both paths are available simultaneously.

On real ArduPilot adapters, the backend must assert the firmware resume policy
(`MIS_RESTART` / `AUTO_RESUME`) before exposing resume as a no-rewind control; see
ADR 0024.

The word "Approve" is not used in the operator-facing UI. The approval concept was
removed by ADR 0021. Internal draft statuses (`proposed`, `planning`, `exported`,
`cutover_pending`) are pipeline plumbing not surfaced in the sidebar.

### Concurrency and edit-lock invariants

- All edits carry `client_version` for optimistic CAS. The backend rejects stale writes with `409 Conflict`.
- Editing a locked revision (`approved`, `executing`, `completed`) forks a new client-authored revision with provenance inheritance rather than mutating in place.
- No mutation of an executing revision is permitted. The widget enforces this with short-circuit gesture handlers; the backend enforces it server-side.
- The `Execute mission` button is shown only for the operation's **active** revision. Attempting to execute a sibling revision is rejected with `stale_revision`.

### Safety invariants

- The edit lock during execution is not bypassable from the frontend.
- The map widget never issues low-level MQTT commands directly.
- Stop always holds the vehicle in place — it does not trigger RTL. The vehicle waits for manual operator control.
- Pause and stop commands are available from both the sidebar buttons and AI chat simultaneously.

The Mission CRUD and Safety Invariants sections above describe **Strict mode** behaviour — the shipped default for real-rover builds. [ADR 0021](../../cross-cutting/decisions/0021-mission-lifecycle.md) also defines **Confirm** (operator confirms an AI-armed execution via a banner) and **Autonomous** (sim-build default; AI may execute directly). Mode lives in `Settings → Mission Lifecycle`. The cross-cutting invariants are: no client-side mutation of executing missions, no silent overwrites of authoritative state, and no invented backend contracts. ADR 0021 also defines the **flat Mission sidebar** (one row = one Mission, with `#index`, editable name, `origin`, `origin_chat_id`) and the **Visible / Selected / Active** three-state UI.

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
