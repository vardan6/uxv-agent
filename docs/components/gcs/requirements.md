# GCS — Requirements

What the Ground Control Station must provide from the operator's point of view. The product-level source of truth for the operator workflow, page behavior, safety invariants, and acceptance criteria.

Companion documents:

- [design.md](./design.md) — implementation strategy, runtime seams, file layout, current limitations.
- [internals/api-and-runtime.md](./internals/api-and-runtime.md) — HTTP/WebSocket surface, control model, settings model.
- [../../current-state.md](../../current-state.md) — what ships today.

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

The `/ai` page hosts a reusable `MapWidget` (Leaflet + `L.CRS.Simple`, local scene metres) that renders the rover's operating scene and all mission overlays. The map is vehicle-aware — it reads the active `VehicleProfile` to populate property panels and enforce vehicle-specific dispatch rules.

The map widget must:

- render the terrain scene (scene objects, road graph, blockages, corridors) at all times
- display a `MissionListPanel` showing revisions grouped by operation, with status badges
- render mission overlays (AI-proposed and operator-authored) as distinct visual layers with provenance-aware per-waypoint styling (`ai` / `user` / `ai+edited`)
- track and display the live vehicle position via the `/ws` telemetry stream (polling fallback at 2 s)
- support a `SelectionPanel` that shows waypoint-level details and provenance for any selected waypoint
- support a context menu (right-click or long-press) for point-level actions (insert waypoint before/after, delete, set as home, detach from AI proposal)
- display hint toasts for gestures and a keyboard help overlay

### Mission CRUD

The map widget is the primary mission authoring surface on `/ai`. No separate Missions page exists.

Operators must be able to:

- **Create a mission from scratch** using `➕ New mission` — lay down waypoints manually on the map
- **Review AI-proposed revisions** — the agent emits a revision; the map renders it immediately
- **Edit AI-proposed or operator-authored revisions** — drag waypoints, add/delete waypoints, reorder
- **Approve a draft** (does not execute) using the "Approve draft" button; semantics: approval locks the revision for the `Execute mission` gate
- **Execute mission** — a separate, explicit second action that hands the approved revision to the flight controller
- **Export plan** — export the approved revision as a `.plan` file without executing

The three verbs are **Approve draft**, **Execute mission**, and **Export plan**. The word "Accept" is not used.

### Concurrency and edit-lock invariants

- All edits carry `client_version` for optimistic CAS. The backend rejects stale writes with `409 Conflict`.
- Editing a locked revision (`approved`, `executing`, `completed`) forks a new client-authored revision with provenance inheritance rather than mutating in place.
- No mutation of an executing revision is permitted. The widget enforces this with short-circuit gesture handlers; the backend enforces it server-side.
- The `Execute mission` button is shown only for the operation's **active** revision. Attempting to execute a sibling revision is rejected with `stale_revision`.

### Safety invariants

- Approval does not execute. Execution requires a second explicit operator action.
- The edit lock during execution is not bypassable from the frontend.
- The map widget never issues low-level MQTT commands directly.

## Cross-Cutting Behavior

### Freshness Indicators

Throughout the UI, indicators distinguish:

- **fresh**: data received recently, within the configured threshold
- **stale**: data older than the threshold but still present
- **absent**: no data available

The operator should treat stale telemetry as suspect — the rover may not actually be where the dashboard shows.

### Single-Operator Assumption

The current GCS is single-instance. Multi-browser use within one GCS works (focus determines who drives), but multi-GCS deployment is not fully defined yet. See [roadmap.md](../../roadmap.md) for the planned direction.

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
