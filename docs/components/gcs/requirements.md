# GCS — Requirements

What the Ground Control Station must provide from the operator's point of view. The product-level source of truth for the operator workflow, page behavior, safety invariants, and acceptance criteria.

Companion documents:

- [design.md](./design.md) — implementation strategy, runtime seams, file layout, current limitations.
- [design/api-and-runtime.md](./design/api-and-runtime.md) — HTTP/WebSocket surface, control model, settings model.

If documents disagree:

- this document wins for product intent and operator-visible behavior
- `design.md` wins for implementation details

## Pages At A Glance

The Ground Control Station serves these browser pages:

| Page | URL | Purpose |
|---|---|---|
| Mission Console | `/` (`/mission-console`) | Primary operator workspace — a composable widget surface (map, AI chat, video, telemetry, replay) |
| Drive Console | `/dashboard` | Live rover teleoperation: video, drive controls, telemetry (renamed from "Dashboard") |
| Replay | `/replay` | Inspect recorded sessions |
| Settings | `/settings` | Configure connectivity, video, LLMs, and import/export |
| MQTT Setup | `/setup/mqtt` | Edit and reconnect the broker connection |
| AI Agent | `/ai` | Chat / Agent today; converging toward a single primary Agent experience |

The AI page is documented separately in the [AI Agent component](../ai-agent/requirements.md).

The frontend is being rebuilt greenfield as a widget-based **Operator Console**
(see §Operator Console below). The stack and migration are decided in
[ADR 0030](../../cross-cutting/decisions/0030-greenfield-operator-console-frontend.md);
the headless architecture and data layer in
[ADR 0031](../../cross-cutting/decisions/0031-headless-full-architecture-and-frontend-data-layer.md);
implementation in [design/operator-console.md](./design/operator-console.md).

## Mission Console (`/`, `/mission-console`)

Mission Console is the primary operator workspace for mission-focused work. It
combines the replay-session list, mission map and Mission management surface,
and AI Agent chat in one page. Existing replay, mission-map, Mission, and AI
Session behavior should be reused here rather than forked into separate product
logic.

## Operator Console (Widget Workspace)

The Mission Console is being rebuilt as a composable **widget workspace**. From the
operator's point of view:

- **Widgets** are self-contained views — map, AI chat, video feed, drive controls,
  telemetry, replay sessions, replay playback, status bar. Each can be added from
  an **Add Widget** palette.
- **Free-form layout:** move any widget anywhere; snap/dock to any edge; split;
  stack as tabs; or **float** a widget over the workspace. A widget added from
  the palette **splits** the current pane rather than joining a tab stack, so
  newly added widgets are visible immediately; stacking is an explicit gesture
  (drag onto a tab strip). This applies identically inside a Widget Group.
- **Widget Groups:** the operator can create a named rectangular container that
  holds **several widgets visible at once** in their own arrangement, and move,
  dock, or resize that container **as a single unit** with its internal
  arrangement preserved. A Widget Group is distinct from a **tab stack**, where
  only one widget is visible at a time. A Group has **no header of its own**:
  its title, close, rename, "add widget" and "save template" controls all live
  on the Group's tab and its right-click menu, so the container spends no
  vertical space on duplicate chrome. Its body is still visually distinguishable
  from ordinary panel chrome so it reads as a container. A Group cannot be
  placed inside another Group, and Groups do not appear on compact/small
  screens — the operator sees their member widgets directly. Closing a
  populated Group destroys its member widgets after a confirmation prompt —
  there is no partial/evict option.
- **Moving widgets between containers:** the operator can move a widget from the
  main workspace into a Widget Group, out of a Group, and between two Groups —
  including into a Group that is currently **empty**, so dragging out the last
  widget is always recoverable. Where the widget will land must be visible
  *before* the drop: the receiving container highlights the exact target region.
  A move never destroys the widget — if the destination refuses it, it stays
  where it was. Every such move is also reachable **without dragging**, from a
  menu on the widget itself; that menu is the only path in or out of a
  **popout window**, since a drag cannot cross OS windows.
- **Group templates:** the operator can save a Group's widget composition and
  arrangement as a named, reusable template (not its live content — a saved
  template starts each widget fresh) and apply a saved template later to
  create a new Group elsewhere in the workspace. Saving under an existing
  name prompts to overwrite; deleting a template prompts for confirmation.
- **Compact chrome:** panel tab bars must not dominate the workspace at the
  ~12-widget scale, while still identifying each widget and remaining draggable
  for docking. Non-goal: vertical/side-mounted tab bars — see
  [ADR 0033](../../cross-cutting/decisions/0033-workspace-chrome-density-and-widget-groups.md).
- **Popout windows:** a widget can be ejected into a **separate OS window**,
  draggable anywhere including another monitor (e.g. a minimal video or drive
  window beside the operator). This is desktop-only.
- **Workspaces:** the operator can **save and restore** named layout arrangements
  ("Workspaces"). A widget being present or absent never changes whether the
  underlying functionality works — recording, control, and AI execution run
  server-side regardless of what is shown.
- **Multiple instances:** *some* widget types support multiple instances (e.g.
  several AI chats each pinned to a different session, multiple video feeds, or —
  designed for but not shipped in the first milestone — several maps). Other widgets
  are **singletons** (Drive Controls, AI Session List, Replay Sessions, Replay
  Playback, Status Bar). Which types are multi-instance vs singleton is explicit in
  the widget catalog in
  [design/operator-console.md](./design/operator-console.md). A Map widget carries
  its own layer / object / visibility controls; visibility toggles are per-map.

The architecture that guarantees "no widget depends on another widget" is in
[ADR 0031](../../cross-cutting/decisions/0031-headless-full-architecture-and-frontend-data-layer.md).

## Client Surfaces (Web, CLI, Mobile)

The GCS runtime is a complete, frontend-agnostic application. Clients consume the
same HTTP/WS contract:

- **Web** — the primary Operator Console (above).
- **CLI** *(future)* — a headless text client for AI chat, commands, and status.
  Video and map are out of scope for the CLI.
- **Mobile web** — video, drive controls (touch d-pad), telemetry, and AI chat work
  responsively. **Full free-form docking is desktop-only**; mobile uses a
  simplified stacked / curated layout or a chosen Workspace. This is a documented
  limitation, not a defect.

## Drive Console (`/dashboard`)

> Renamed from "Dashboard". The Drive Console is the teleoperation surface
> (live video + drive controls + telemetry); it pairs with the Mission Console
> (planning/oversight). Existing behavior below is unchanged by the rename.

The Drive Console is the manual-control and live-monitoring surface. It is split
into a telemetry/state area and a live camera area, with a compact header for
status and navigation.

### What The Operator Sees

- **Camera feed**: a live JPEG stream of the rover's POV camera, delivered through the MQTT → WebSocket bootstrap path. A status indicator shows whether the feed is fresh. A Video widget may also render a preset-driven telemetry OSD overlay on top of the frame.
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

> **Direction (greenfield):** Settings is being rebuilt VS Code-style — a top
> **search** line, a left Explorer-style **category tree**, and a **filterable
> parameter→value list**. The underlying config JSON and its values are
> **unchanged**; only the editing surface changes. The full MQTT editor moves into
> the Connectivity category. **Open question (undecided):** whether a lightweight
> standalone first-run `/setup/mqtt` flow is retained as an onboarding gate, or
> dropped entirely as a pure duplicate of Settings → Connectivity. Current lean:
> merge into Settings. Until the operator decides, the standalone-page behavior in
> §MQTT Setup below describes the *current* implementation, not settled greenfield
> intent. The configuration areas and behaviors below remain the source of truth
> for *what* is configurable; see
> [design/operator-console.md](./design/operator-console.md) §Settings for *how*.

### Connectivity Tab

Edit MQTT broker host, port, topic prefix, and topic names. Saving applies live — the GCS reconnects without restart. Today the same surface is also reachable standalone at [MQTT Setup](#mqtt-setup-setupmqtt) for first-run onboarding; whether that standalone page is retained in the greenfield console is an open question (see the Settings direction note above).

### Video Tab

Choose video mode flags. Changes are persisted and broadcast to all connected browsers.

### OSD Tab

Manage **named OSD presets** for live video widgets.

The operator can:

- create, rename, duplicate, and delete OSD preset instances
- configure which built-in telemetry lines a preset shows
- choose the line order and screen corner used by a preset
- adjust basic presentation controls needed for readability, such as compactness or opacity

The first milestone keeps the OSD model **structured, not free-form**. Presets are
assembled from a fixed catalog of built-in runtime lines (position, speed/heading,
GPS, power, camera/runtime freshness). Arbitrary scripting, custom expression
languages, and pixel-perfect drag layout are out of scope for this stage.

Each **Video widget instance** can apply one saved preset independently, or show no
OSD at all. The applied preset is part of that widget's own saved view state, so it
travels with the Workspace layout. Editing a preset updates every Video widget that
currently uses that preset.

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

- MQTT
- simulation
- video
- appearance
- AI settings
- LLM providers
- model routing rules

Important behavior:

- **export does not include raw API keys** — only secret reference names
- **missing sections in an imported file are preserved** — older JSON files do not erase newer settings
- **import previews changes before applying** — operator confirms before settings change

## MQTT Setup (`/setup/mqtt`)

> **Current implementation** (greenfield disposition undecided — see the Settings
> direction note above). In the greenfield Operator Console the full MQTT editor
> moves into Settings → Connectivity; whether this standalone page survives as a
> lightweight onboarding gate or is dropped as a duplicate is an open question
> (lean: merge).

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
- surface, on each mission row: a status stripe + status label, the mission's vehicle/profile icon — the profile the mission is *bound to*, falling back to the active selection only for missions authored before profiles were stamped, and a neutral "unknown" glyph rather than the ground-vehicle one when the kind cannot be resolved — a created-at date, an origin badge that distinguishes manual (👤), AI (🤖), and AI-then-operator-edited (✏️), an inline-renamable name (auto-numbered when untitled), and an edit ⇄ done toggle
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

### Runtime Responsiveness And Recovery

- Control handling, telemetry freshness, and operator Stop actions must remain responsive while replay persistence, analytics, RAG ingestion, or AI provider work is slow.
- A slow or disconnected browser must not delay other browser clients or cause unbounded retention of telemetry, video, or AI-stream data. High-rate live data may be coalesced to the newest value; the operator-facing state remains explicitly fresh, stale, or absent.
- Long-running operator jobs and streams must expose a terminal status, bounded resource use, and a defined cancellation/shutdown outcome. Background failures must be observable to operators and service logs.
- Browser refresh, navigation, or WebSocket loss must not by itself stop a server-owned mission execution. An intentional GCS-server shutdown while one is active must warn, identify the active Mission, and require explicit operator confirmation. The recovery contract after a GCS-server process failure is defined by ADR 0023; neither policy is inferred from browser connection state.

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
