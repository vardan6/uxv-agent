# Simulator Design

## Purpose

The simulator is the vehicle-side runtime of the project. It provides a simulated rover with physics and terrain interaction, a local operator view, MQTT control intake, telemetry generation, simulated camera output, and the settings and diagnostics needed during development and demos.

For requirements, see [requirements.md](./requirements.md).
Topic-level implementation internals are folded into this file at the end (terrain-scene, technical-details, rover-physics-tuning, rover-sim-next-phase-1, shadow-enhancement).

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


---

# Merged from internals/ (2026-05-26)

The following sections were previously maintained as separate files under `docs/components/simulator/internals/`. Pass-1 + Pass-2 trim left them ≥80% design-shaped, so they have been folded into this design.md verbatim. ADR 0010 (which named the `internals/` tier) is superseded by this consolidation.


---

<!-- source: docs/components/simulator/design.md -->

# Rover Physics Tuning

## Purpose

This document defines the simulator-side tuning method and acceptance behavior
for rover physics.

It exists to keep tuning work repeatable without freezing transient parameter
values into documentation.

For requirements, see [../requirements.md](../requirements.md). For adjacent
simulator design context, see [./technical-details.md](./technical-details.md).

## Fixed Evaluation Route

The rover should be tuned against one fixed manual route with four checkpoints:

1. straight bump test
2. uphill climb
3. side-slope traverse
4. downhill turn

Each tuning pass should be evaluated against the same route and the same
acceptance rules.

## Acceptance Behavior

- hill climbing must remain at least as capable as the accepted baseline
- suspension should show one main rebound and at most one small follow-up
  motion after a bump, drop, or landing
- low-speed steering should keep strong bite for precise placement and climbing
- medium-speed and high-speed turning may drift, with the rear stepping out
  first in a mild progressive way
- side-slope behavior should slide mildly before wheel lift or rollover when
  near the limit
- downhill turns should remain placeable with steering and throttle, not wash
  out uncontrollably

## Observability

- physics debug telemetry remains the low-level readout for pitch, roll, wheel
  contacts, throttle, and steering
- the simulator UI should surface the fixed manual test route and short
  pass/fail reminders so the operator validates the same behavior every time
- visual-only geometry changes should stay decoupled from rover-dynamics
  conclusions unless explicitly promoted into physics

## Tuning Sequence

The accepted order of work is:

1. suspension settling
2. turn and drift balance
3. hill traction and climb
4. side-slope stability

This order is intentional because slip-balance changes can invalidate climb and
side-slope results if introduced later.

## Non-Goals

These are outside the scope of this tuning document:

- automatic checkpoint detection
- automatic scoring or route verdicts
- tower mass or collision contribution
- extreme rock-crawling targets


---

<!-- source: docs/components/simulator/design.md -->

# rover-sim-next Phase 1 Contract

## Purpose

This document defines the first usable compatibility contract for
`rover-sim-next`.

Phase 1 is the point where `rover-sim-next` can act as a simulator backend for
the existing GCS without requiring a GCS-side protocol rewrite.

## Phase 1 Scope

Phase 1 should satisfy these compatibility outcomes:

- `rover-sim-next` launches as a real simulator process
- one rover can be driven from the current GCS
- telemetry is published on the existing MQTT telemetry path
- the GCS can display rover movement and status without simulator-specific
  parser changes
- backend identity is explicit as `rover-sim-next`
- `3d-env` remains runnable during the transition

This phase is intentionally about backend compatibility, not full simulator
fidelity.

## Control Contract

`rover-sim-next` should adapt to the current GCS control payload rather than
redesigning operator control semantics in Phase 1.

Design rules:

- subscribe to the existing control topic
- translate current browser control payloads into simulator actuation
- define safe defaults when no control input is present
- keep the first control loop explicit and deterministic

## Telemetry Contract

`rover-sim-next` must publish telemetry in the minimum shape already expected
by the GCS.

Required fields:

- `timestamp`
- `backend`
- `position.x`
- `position.y`
- `position.z`
- `gps.lat`
- `gps.lon`
- `gps.alt`
- `orientation.heading_deg`
- `speed.m_s`
- `speed.km_h`
- `camera.mode`
- `camera.video_endpoint`
- `power.battery_pct`
- `power.voltage_v`
- `power.current_a`
- `power.temperature_c`

Compatibility rules:

- `backend` must identify the source as `rover-sim-next`
- telemetry cadence must remain stable enough for the current UI
- the basic live dashboard path should work without GCS-side parser changes

## Coordinate And Map Rule

The simulator should use an ENU-style local frame internally.

The site origin must be configurable so local simulator pose can map
deterministically into GPS-compatible values.

Phase 1 coordinate intent:

- local simulation and control logic use the local frame
- GPS fields exist as a compatibility layer for current GCS consumers
- the same coordinate foundation should later support both live-map and replay
  use without redesign

## Camera Compatibility Rule

Phase 1 only needs enough camera behavior to keep the current GCS workflow
usable.

Design rule:

- choose the simplest camera path that preserves end-to-end usability
- do not block simulator bring-up on the final media architecture
- keep the camera contract explicit in config

## Asset Rule

Early rover and world assets may be rough development assets, but they must not
become the long-term source of truth.

Design rule:

- keep the file layout ready for later authoritative asset replacement
- preserve simulator/GCS contracts when assets are replaced

## Deferred Beyond Phase 1

These do not block the Phase 1 compatibility milestone:

- simulator-side replay logging
- richer live-map behavior
- synchronized replay/video playback
- CAD-derived authoritative assets
- high-fidelity rover dynamics beyond a first stable controllable model


---

<!-- source: docs/components/simulator/design.md -->

# Shadow Enhancement

## Purpose

This document records the durable shadow-rendering rules for the Panda3D
simulator.

The goal is stable, readable outdoor shadows without coupling the simulator to
a large custom-shader maintenance burden.

## Primary Shadow Rule

The shadow pass should use reverse culling rather than relying on aggressive
depth-offset tuning to hide acne.

Design rule:

- render back faces into the shadow map
- keep color writes off for the shadow pass
- use only a small depth offset as a safety net

Why this rule exists:

- front-face shadow casting causes self-shadow acne on terrain and other
  tessellated geometry
- reverse culling removes that failure mode at the geometry level instead of
  trying to bury it with bias
- large depth offsets create peter-panning, so they are not the primary fix

For single-sided terrain meshes, reverse culling also prevents the terrain
from self-shadowing into the shadow map.

## Lighting Intent

Outdoor lighting should preserve three visual properties:

- a directional sun that provides the main shadow shape
- ambient or fill lighting that keeps shadowed areas readable without washing
  out contrast
- a world-stable shadow frustum so artifacts do not appear to swim with the
  rover

Shadow quality improvements should keep those three properties intact.

## Shader Path Rule

The legacy Panda3D auto-shader remains the default render path.

`panda3d-simplepbr` is allowed only as an opt-in path for experimentation.

Reason:

- the current rover and terrain assets are vertex-color oriented and were not
  authored as a full PBR material stack
- enabling PBR by default changes scene color and shadow perception enough to
  count as an art-direction change, not just a shadow-quality change

Implication:

- if `simplepbr` is used, it must remain behind an explicit opt-in switch
- default visual acceptance should be judged against the legacy path

## Quality Ceiling And Escalation Path

The acceptable escalation order is:

1. fix acne and peter-panning with shadow-pass geometry rules first
2. add modest filtering or bias improvements only if the default path still
   needs them
3. consider PSSM or cascaded-shadow techniques only if the simulator needs a
   meaningfully larger quality jump

PSSM stays deferred because it requires a broader custom-shader commitment
across terrain, rover, and prop rendering.

## Durable Decision Summary

- reverse-cull shadow casting is the canonical acne fix
- depth offset is a minor safety control, not the main solution
- `simplepbr` stays opt-in until the art/material pipeline is intentionally
  reworked
- PSSM is a later-tier option, not the default next step


---

<!-- source: docs/components/simulator/design.md -->

# Simulator Technical Details

## Purpose

This document records the durable simulator runtime rules that shape how the
simulator interacts with MQTT and the GCS.

## MQTT Runtime Contract

The simulator uses MQTT for three distinct responsibilities:

- subscribe to control input
- publish rover state telemetry
- publish camera frames

Telemetry should continue to include the current GCS-facing essentials:

- timestamp
- position
- GPS-compatible location
- orientation
- speed/velocity
- camera mode metadata
- power placeholders

Camera publication remains a separate MQTT media path, but it is governed by
the same publish policy as state telemetry.

## GCS Presence Semantics

The simulator treats a GCS as active only when all of these are true:

- the presence payload marks it as active
- the payload contains a recent timestamp
- that timestamp is still inside `gcs_presence_timeout_ms`

Presence should remain keyed by `gcs_id`.

## Publish Gating Rule

The simulator uses one outbound publish gate for all MQTT publishing.

Design rule:

- state telemetry publish is blocked when policy disallows outbound publishing
- camera-frame publish is blocked by the same policy

This rule is important because allowing camera publication while blocking state
telemetry would still leak bandwidth and partially bypass operator policy.

## Rover Baseline Boundaries

The accepted rover baseline currently assumes:

- graded dirt roads, pads, and light uneven ground are in scope
- extreme rock crawling is out of scope
- the tower remains visual-only in this phase and does not contribute mass,
  inertia, or collision

These boundaries should remain explicit while simulator tuning continues.

## Current Practical Limits

These limits are still part of the runtime boundary:

- camera transport is still MQTT JPEG publishing
- power values remain placeholders rather than a modeled power system
- the tuning route is an operator reminder, not an in-world checkpoint system


---

<!-- source: docs/components/simulator/design.md -->

# Terrain Scene Manifest

## Purpose

The terrain scene manifest is the single source of truth for the current `3d-env` world geometry and map data.

Authoritative artifact: `config/terrain_scene.v1.json` (validated against `config/terrain_scene.schema.json`).

## Current Model

The manifest is a text-based JSON file that contains the final expanded scene representation.

It explicitly defines:
- terrain size and heightfield samples
- terrain coordinate frame and artificial GPS georeference
- road centerlines and widths
- spawn points
- pads
- solar panels and frames
- building parts
- start-hub and charger parts
- rocks and boulders
- trees
- collision proxies and route-planning metadata where available

Runtime code must not invent object names, counts, coordinates, or dimensions. The simulator and GCS read them from `terrain_scene.v1.json`.

## Virtual GPS

The scene uses local metric coordinates as the authoritative position model:
- `x`: east in meters
- `y`: north in meters
- `z`: altitude in meters

`coordinate_system.georeference` defines an artificial GPS anchor for compatibility with rover telemetry fields. The conversion is a local tangent-plane approximation: moving one meter north in the simulator changes latitude by roughly one real meter, and moving one meter east changes longitude by roughly one real meter at the configured origin latitude.

This GPS is not read from the operator laptop or browser. It is deterministic mock GPS derived from the rover's virtual 3D position.

## Why JSON Is Used Here

JSON is used as the project source-of-truth format because both Python simulator code and JavaScript/browser-facing GCS code can consume it directly. It is also easy to validate and review in Git.

Future CAD/simulator exports can be generated from this manifest:
- `.usda` for NVIDIA Isaac Sim / OpenUSD workflows
- `.glb` or `.gltf` for simulation-ready visual meshes
- collision mesh files for physics
- STEP or other CAD references for authoritative engineering assets

The manifest remains the composition/index file even when individual objects later reference professional CAD-derived assets.

## Source And Pipeline Discipline

Do not fix terrain, charging-station geometry, roads, or colliders by only patching `config/terrain_scene.v1.json`. Treat that file as a generated runtime artifact.

When redesigning the start hub, charging station, flat apron, roads, or physics collision proxies:

1. Update the source that owns the scene design first (currently the compact seed file plus the generator script).
2. Regenerate `config/terrain_scene.v1.json`.
3. Run the scene validator.
4. Run the simulator and test rover driving from spawn, docking-area exit, road entry, object collision, and no floating/buried station parts.
5. When a broader map database or BUS-style synchronization pipeline exists, run that pipeline after the source update so every map representation is rebuilt from the same source design.

If a future map synchronization layer adds a transformation config or sync generator, the rule stays the same: update the source, build all derived map versions, validate the final `terrain_scene.v1.json`, then test in the simulator.

## Editing Rule

Edit the compact generator input only when you intentionally want to regenerate the whole scene.

If the manifest is hand-edited, run the validator before using it. Long term, the compact seed file should either be removed or clearly archived once the expanded manifest is the only maintained source.

