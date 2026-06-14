# Simulator Design

## Purpose

The simulator is the vehicle-side runtime of the project. It provides a simulated rover with physics and terrain interaction, a local operator view, MQTT control intake, telemetry generation, simulated camera output, and the settings and diagnostics needed during development and demos.

For requirements, see [requirements.md](./requirements.md).
Per-topic design files live under [`design/`](./design/) — terrain-scene, technical-details, rover-physics-tuning, rover-sim-next-phase-1, shadow-enhancement.

Sources consolidated here:
- `docs/archive/simulator/2026-05-16-simulator-overview.md` (primary)
- `docs/archive/simulator/2026-05-08-platform-plan.md` (transition and rover-sim-next plan)
- `docs/archive/simulator/2026-04-05-initial-hl-design.md` (historical context and first architectural decisions)
- `docs/archive/simulator/2026-04-05-phase1-3D-Simulator.md` (Phase 1 scope and world redesign history)
- `docs/archive/simulator/2026-04-05-mqtt-plan-canonical.md` (canonical Phase 2 MQTT control/telemetry contract)
- `docs/archive/simulator/2026-05-15-center-station-physics-grill.md` (center-station redesign decisions)

---

## Implementation Status

| Area | Status |
|---|---|
| Panda3D + Bullet 3d-env simulator | **Active** — current working baseline |
| Rover physics tuning loop | **Complete** — first accepted baseline in place |
| MQTT control/telemetry | **Implemented** |
| MQTT camera-frame publication | **Implemented** |
| GCS presence-aware publish gating | **Implemented** |
| Settings UI (MQTT, bindings, appearance, import/export) | **Implemented** |
| Terrain scene manifest (`terrain_scene.v1.json`) | **Implemented** |
| `rover-sim-next` ROS 2/Gazebo scaffold | **Scaffold only** — side path in the repo, not a working backend |
| Simulator-side replay logging | **Deferred** — until `rover-sim-next` works end-to-end |
| Authoritative CAD/asset pipeline | **Not started** |

---

## Architecture

### Technology Stack

The current `3d-env` simulator is built on:
- **Python** — runtime language
- **Panda3D** — scene graph and desktop window management
- **Bullet physics** (via Panda3D integration) — rover vehicle physics, terrain collision, object colliders

This stack was chosen in the earliest design phase when the project was prototyping quickly. It remains the working baseline.

The current `rover-sim-next` scaffold targets:
- **ROS 2** — runtime and topic framework
- **Gazebo** — physics and world simulation

This choice provides a clearer migration toward robotics-oriented workflows and better long-term fit for formal robot description and world composition.

### Module Structure (`3d-env/simulator/`)

| Module | Responsibility |
|---|---|
| `main.py` | main runtime loop, telemetry generation, publish gating, scene object creation |
| `mqtt_bridge.py` | MQTT client, control subscription, presence tracking, telemetry and camera publish |
| `rover.py` | BulletVehicle rover dynamics, suspension, steering, physics parameters |
| `terrain.py` | manifest-backed terrain heightfield, visual mesh, road coloring, Bullet collision mesh |
| `camera.py` | follow/POV camera handling and POV buffer capture |
| `gui.py` | top menu, status bar, telemetry overlay |
| `settings_gui.py` | settings dialogs, MQTT config, persistence |

---

## Current Simulator Behavior

### What Is Implemented

- Panda3D desktop simulator with Bullet physics
- keyboard driving
- follow and POV camera modes
- telemetry HUD and status bar
- physics debug telemetry in the HUD
- manual test-route reminder in the HUD for rover tuning passes
- deterministic large terrain with mission-style landmarks
- MQTT control subscription
- MQTT telemetry publication
- MQTT camera-frame publication
- settings UI for MQTT, key bindings, appearance, import/export
- menu control for telemetry publishing policy
- automatic suppression of outbound publishing when no active GCS is available in `auto` mode
- explicit `terrain_scene.v1.json` manifest as terrain and scene source of truth

### Control Sources

Currently supported:
- local keyboard input
- MQTT control input from the GCS

Remote MQTT input has a failsafe timeout: stale control input is neutralized after `250 ms` silence.

### Telemetry Publishing Policy

| Policy | Behavior |
|---|---|
| `auto` | publish only while at least one GCS instance is active and fresh on the presence topic |
| `force_on` | always publish |
| `force_off` | never publish |

This policy gates both telemetry and camera frame publishing. Disabling only state telemetry while leaving camera frames ungated would still leak bandwidth.

---

## MQTT Contract (Simulator Side)

This section captures the canonical Phase 2 MQTT contract. For the system-wide topic model and presence contract, see [cross-cutting/architecture.md](../../cross-cutting/architecture.md).

### Topic Prefix And Names

| Key | Default |
|---|---|
| `topic_prefix` | `/projects/remote-rover` (configurable) |
| `control_topic` | `control/manual` |
| `state_topic` | `telemetry/state` |
| `camera_topic` | `camera-feed` |
| `gcs_presence_topic` | `gcs/presence` |

Full topics: `{topic_prefix}/{topic_name}`.

### Control Topic

Topic: `{topic_prefix}/{control_topic}`

Payload fields:
- `mode`: `"analog"` or `"digital"`
- `throttle`: float `[-1.0, 1.0]` (optional in digital mode)
- `steering`: float `[-1.0, 1.0]` (optional in digital mode)
- `buttons`: `{ forward, backward, left, right, stop, camera_toggle }`
- `source`: string (optional)
- `timestamp`: number (optional)

Control mechanics:
- digital mode uses fixed preset throttle/steering step values
- analog mode uses proportional values directly
- arbitration: last-writer-wins between local keyboard and MQTT control
- failsafe: if a control frame's age exceeds `250 ms`, remote throttle/steering are neutralized

### State Topic

Topic: `{topic_prefix}/{state_topic}`

Minimum telemetry fields the GCS depends on:
- `timestamp`
- `backend` (identifies `3d-env` or `rover-sim-next`)
- `position.x`, `position.y`, `position.z`
- `gps.lat`, `gps.lon`, `gps.alt`
- `orientation.heading_deg`
- `speed.m_s`, `speed.km_h`
- `camera.mode`, `camera.video_endpoint`
- `power.battery_pct`, `power.voltage_v`, `power.current_a`, `power.temperature_c`

Additional fields currently published:
- IMU placeholders (accel, gyro)
- barometer altitude
- physics debug state (wheel contacts, pitch, roll, throttle, steering)
- manual tuning-route reminder metadata used by the HUD

### Camera Topic

Topic: `{topic_prefix}/{camera_topic}`

Current source: POV offscreen buffer capture, published as JPEG bytes.

### Publish Rates

- telemetry: `2 Hz` default (configurable via `telemetry_hz`)
- control publish loop: `20 Hz` default (configurable via `control_hz`)

---

## Terrain And Visual World

The current world includes a `400 × 400` terrain area driven entirely by an explicit scene manifest at `config/terrain_scene.v1.json`.

Key terrain features:
- deterministic valley and hill shaping
- two solar plant areas
- one central operations building
- connecting roads and flattened vehicle corridors
- larger trees and mixed-size rocks

The simulator runtime reads terrain heightfield data, roads, spawn points, and static object definitions from the manifest. Object names, counts, coordinates, and dimensions must not be hard-coded in simulator scripts.

### Virtual GPS

The scene uses local metric coordinates as the authoritative position model:
- `x`: east in meters
- `y`: north in meters
- `z`: altitude in meters

`coordinate_system.georeference` defines an artificial GPS anchor for MQTT telemetry compatibility. Moving one meter north changes latitude by roughly one real meter; moving one meter east changes longitude by roughly one real meter at the configured origin latitude. This is deterministic mock GPS derived from rover position, not from hardware.

### Terrain Source Discipline

The expanded `config/terrain_scene.v1.json` is the runtime source of truth. Do not patch it directly without also updating the generator.

To regenerate:
```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
python3 tools/generate_terrain_scene.py
python3 tools/validate_terrain_scene.py
```

---

## Active Rover Tuning (3d-env Baseline)

The first rover physics tuning loop is complete and accepted. For the detailed tuning targets, parameters, and test sequence, see [design.md](./design.md).

Accepted behavior summary:
- quick suspension settling after bumps/drops
- strong low-speed steering bite
- mild progressive rear-led drift at medium and high speed
- sliding before rollover on side slopes
- controllable downhill turns

The visual-only tower does not contribute to physics in the current baseline.

---

## Center Station Design Decisions

These decisions were agreed in a grill-me session on 2026-05-15 (source: `center-station-physics-grill.md`). They govern the center start-hub/charging-station area redesign.

**1. Replace The Center Area, Do Not Patch It.** Prior patch attempts did not produce a good result. The area must become physically logical and stable by design, not by patching the raised/hanging/edge problems that existed before.

**2. Preserve High-Level Coordinates.** Keep the start hub and spawn near `(0, 20)`. The redesign changes geometry quality, not the whole world layout.

**3. Make Terrain And Geometry Physically Logical.** The center area should be stable because the terrain and station geometry are sane — not because the rover is artificially constrained. Design targets: flat home-base apron, smooth terrain transitions into roads and surrounding natural terrain, no cliff-like pad edges near spawn, no floating or buried station parts, clear natural exits.

**4. Avoid Invisible Barriers.** Do not use invisible barriers as the primary stability mechanism. Visible physical barriers may exist only where they make real-world sense as site features.

**5. Center Redesign Before Rover Tuning.** Bad local terrain and object colliders make rover tuning unreliable. Fix the home-base geometry first, then tune rover physics against the corrected environment.

**6. Charging Hardware Fidelity Is Secondary For Now.** The charger does not need a precise mechanical connector in the first redesign. A simple visible contact plate or bumper (~`0.25m` to `0.45m` above the apron) is sufficient for a future "touch to charge" trigger.

**7. Use Source/Generator Discipline.** Do not hand-patch only `config/terrain_scene.v1.json`. Update the source (`config/terrain_scene.json` + `tools/generate_terrain_scene.py`), regenerate, validate, then test.

---

## Platform Transition Design

### Transition Goal

The parallel-successor strategy:
- keep `3d-env` working
- build `rover-sim-next` beside it using ROS 2 + Gazebo
- preserve the current MQTT/GCS contract throughout migration
- support both simulators from the GCS during transition
- backend identity must be explicit (`3d-env` vs `rover-sim-next`)

### Implementation Order

1. Make `rover-sim-next` a working simulator backend.
2. Connect it to `gcs_server` without breaking `3d-env`.
3. Stabilize rover model, world model, and coordinate model.
4. Then continue with richer map, logging, replay, and video work.

This ordering satisfies requirements because logging/replay remains planned but is not treated as a prerequisite for the first usable `rover-sim-next` milestone.

### `rover-sim-next` Phase 1 Scope

Required:
- ROS 2 package that actually runs (not just scaffolding)
- Gazebo world that can launch reliably
- rover description with wheels, chassis, and physically meaningful mass/inertia placeholders
- MQTT control bridge into simulator actuation
- telemetry bridge back into the existing GCS contract
- camera path sufficient for current GCS expectations
- site origin and map-position config values carried through the telemetry model
- `3d-env` still works in parallel

Allowed shortcuts in Phase 1:
- simple rover, collision, and world geometry
- practical pseudo-GPS compatibility while the full coordinate model is finalized
- rough AI-generated assets as temporary development assets

Not required for Phase 1:
- professional CAD-derived assets
- final media architecture
- simulator-side replay logging
- final polished map UI inside the main GCS page

### Asset Strategy

**Development assets** (acceptable in early phases):
- Codex-generated or procedurally generated rover body/wheel geometry, terrain props, buildings, obstacles
- treated as temporary development artifacts, not engineering source-of-truth

**Authoritative assets** (later professional replacements):
- real CAD source files, validated dimensions, engineering drawings, approved exported meshes
- replace development assets without changing the MQTT contract, replay model, or GCS behavior

### CAD And Mesh Workflow

Each rover or environment object should eventually be maintained independently:
- separate asset ownership per object
- visual mesh and collision mesh kept separate
- `glTF`/`GLB` as the preferred simulation-ready mesh interchange format
- much simpler collision meshes than visual meshes

Default tooling:
- `FreeCAD` — open CAD authoring for authoritative engineering assets
- `OpenSCAD` — optional for parametric development parts
- `Blender` — mesh cleanup, decimation, UV/material work, export preparation

### Map And Coordinate Model

Recommended local coordinate convention: ENU-style local frame with configurable site origin.

Recommended transform stack:
- `pyproj` for coordinate transforms
- `UTM` as the default practical projection for field deployments
- local tangent-plane conversion for high-accuracy small-site use when needed

Current pseudo-GPS must be treated as a temporary compatibility mechanism only.

Map library decision: `Leaflet.js` for the first live/replay map in the GCS.

The live map and replay map must use the same normalized track model so historical playback and live operation remain semantically consistent.

### Logging And Replay Architecture

For requirements, see [requirements.md § Logging](./requirements.md#logging-and-replay-requirements).

Architecture rules:
- logging in both simulator side and GCS side
- replay from logs captured at either origin
- session model must reserve support for synchronized video without requiring redesign
- simulator-side logging remains deferred until after `rover-sim-next` works end-to-end with the GCS

First storage backend: `SQLite`.

Each recorded session captures:
- session id, source node id, backend type, start/end timestamps, backend version, site/map context
- capability metadata
- reserved fields for camera `pts`, frame index, and external media references (for future synchronized video)

### Headless Mode

The new simulator should support headless or minimally interactive execution early in the plan, for:
- automated contract testing
- repeatable session recording
- replay fixture generation
- non-desktop execution scenarios

---

## Phase Roadmap

| Phase | Status | Summary |
|---|---|---|
| Phase 1 — Foundations and contracts | **Mostly implemented in GCS** | config-backed backend identity, SQLite replay, replay APIs, first Leaflet map, normalized telemetry; remaining: finalize coordinate/site model |
| Phase 2 — GCS map, logging, replay | **Partially implemented** | GCS-side logging, replay APIs, and replay page in place; live dashboard map and simulator-side logging still remain |
| Phase 3 — `rover-sim-next` first working backend | **Scaffold only** | `rover-sim-next/` scaffold exists; real simulator functionality still pending |
| Phase 4 — Modular asset pipeline | **Not started** | authoritative CAD/asset import, modular world composition |
| Phase 5 — Synchronized video and long-term evolution | **Not started** | synchronized video recording/playback, timing for full `3d-env` replacement |

---

## Decisions Summary

| Decision | Choice |
|---|---|
| New simulator sub-project name | `rover-sim-next` |
| Transition mode | parallel successor (not a cutover) |
| Long-term simulator baseline | ROS 2 + Gazebo |
| GCS backend selection | explicit config-backed selector |
| Replay UI | separate GCS page |
| Logging backend (first) | SQLite |
| Initial capture scope | telemetry, control, events |
| Video recording | later |
| Early assets | AI-generated allowed |
| Later assets | professional CAD replaces early assets |
| Default map library | Leaflet.js |
| Default CAD tooling | FreeCAD + optional OpenSCAD, Blender for mesh prep |
| Preferred simulation asset format | glTF/GLB |
| MQTT/GCS compatibility | hard transition requirement |
| Center area strategy | replace geometry by design, not patch |
| Rover physics before center fix | blocked — center redesign comes first |

## Topic-Level Design Files

Detailed per-topic design content lives in sibling files under [`design/`](./design/). This is topic-level organization within the design tier (same stability rules as this file), not a separate tier.

- [`design/rover-physics-tuning.md`](./design/rover-physics-tuning.md) — Rover Physics Tuning
- [`design/rover-sim-next-phase-1.md`](./design/rover-sim-next-phase-1.md) — Rover Sim Next Phase 1
- [`design/shadow-enhancement.md`](./design/shadow-enhancement.md) — Shadow Enhancement
- [`design/technical-details.md`](./design/technical-details.md) — Technical Details
- [`design/terrain-scene.md`](./design/terrain-scene.md) — Terrain Scene
