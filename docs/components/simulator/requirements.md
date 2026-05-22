# Simulator Requirements

## Purpose

This document captures the requirements for the simulation-platform work across both the current `3d-env` simulator and the planned `rover-sim-next` successor.

Sources consolidated here:
- `docs/archive/simulator/2026-05-16-simulator-requirements.md` (primary)
- `docs/archive/simulator/2026-05-16-rover-physics-tuning-prd.md` (physics tuning baseline)

For implementation design, see [design.md](./design.md).
For vocabulary, see [docs/glossary.md](../../glossary.md).

---

## Scope

These requirements apply to the current `3d-env` simulator (the working prototype) and the planned `rover-sim-next` successor project beside it.

The goals are:
- continue supporting the current working prototype during any transition
- define a better long-term simulator platform
- enable phased migration without breaking the existing Ground Control Station

---

## Core Requirements

### 1. Keep The Existing System Working During Transition

The existing `3d-env` simulator must keep working during the transition period.

Any new simulator work must:
- run in parallel with `3d-env`
- work with the existing `gcs_server`
- allow `gcs_server` to continue operating until the new simulator is ready to replace `3d-env`

If needed, `gcs_server` may be updated, but compatibility with the current working system must be preserved during migration.

### 2. Create A New Simulator Sub-Project

A new simulator sub-project (`rover-sim-next`) must be created under the `remote-rover` repository to:
- improve the 3D environment and physics quality
- improve rover/world interaction
- improve modularity and future maintainability
- eventually replace the current `3d-env`

### 3. Preserve And Extend GCS Compatibility

The new simulator must work with the existing `gcs_server` MQTT contract during transition.

Required compatibility surface:
- rover control
- telemetry flow
- camera/video integration
- map integration
- replay visualization in the GCS

The GCS must be able to support both `3d-env` and `rover-sim-next` until the new backend fully replaces the old one.

---

## 3D Simulation Requirements

### 4. Better 3D Environment

The future simulator must improve on the current Panda3D/Bullet setup:
- better terrain and world modeling
- better rover modeling
- better physics behavior
- better rover interaction with the environment
- support for more customizable simulation scenes

The simulator must remain practical for iterative development and must not lose simulation capability while becoming more customizable.

### 5. Strong Physics And Simulation Behavior

The simulator must preserve meaningful 3D simulation capability, including:
- rover motion in a 3D world
- physics-based rover/world interaction
- configurable rover physical properties
- a path to improved realism as better assets and engineering data become available

Customizability must not come at the cost of losing physics or simulation usefulness.

### 6. Prompt-Driven Early Development

During early development, it must be possible to build the rover, environment, and related assets using prompt-driven development with Codex or similar tooling — including early rover geometry, environment geometry, and world objects.

This is explicitly acceptable for early development, even though final project assets should later be replaced by professional CAD-driven assets.

### 7. AI-Generated Assets Are Temporary Development Assets

AI-generated or quickly generated assets are acceptable for development but are not the engineering source of truth. They must be:
- temporary development artifacts
- replaceable by professional assets later
- compatible with the same simulator and GCS interfaces

---

## Physics Tuning Requirements (Current `3d-env` Baseline)

The current `3d-env` simulator is the accepted rover-dynamics baseline. The following requirements apply to the current tuning phase and define the accepted behavioral target.

### Accepted Baseline After First Tuning Loop

- No artificial hill-climb blocking
- Climb capability at least as good as the accepted pre-tuning baseline
- One main rebound and at most one small follow-up motion after bump or drop
- Strong low-speed steering bite for placement and climbing
- Mild progressive rear-led drift at medium and high speed
- Mild sliding before easy rollover on side slopes
- Downhill turns remain controllable without uncontrolled washout
- A larger, lower rover silhouette with a visual-only tower and larger wheels
- A simulator HUD reminder of the four-checkpoint manual route and its pass/fail intent

### Physics Tuning User Stories

1. As an operator, I want the simulator rover to climb natural hills without hidden blocking, so that I can trust its capability model.
2. As an operator, I want stability improvements to preserve or improve current climb performance.
3. As an operator, I want the rover suspension to visibly compress and rebound, so that the model looks and feels mechanically real.
4. As an operator, I want bounce oscillation to die quickly after a bump or drop.
5. As an operator, I want wheel hop and chatter reduced to keep traction and placement believable.
6. As an operator, I want low-speed steering to keep strong bite for placement and climbing.
7. As an operator, I want medium-speed and high-speed turning to allow some progressive drift.
8. As an operator, I want the rear to step out before the front at speed.
9. As an operator, I want throttle corrections to help hold a slide progressively.
10. As an operator, I want the rover to slide mildly before it rolls on side slopes.
11. As an operator, I want side-slope traversal to fail only when the slope is genuinely beyond realistic capability.
12. As an operator, I want downhill braking and slope transitions to feel planted with moderate coasting.
13. As an operator, I want low-speed hill throttle to squat and push rather than wheelie.
14. As an operator, I want the rover to recover from small sideways landings mostly through suspension absorption and tire scrub.
15. As an operator, I want the simulator to expose a fixed short manual test route.
16. As an operator, I want the test route to include a straight bump test, an uphill climb, a side-slope traverse, and a downhill turn.
17. As an operator, I want clear pass/fail criteria for each checkpoint.
18. As an operator, I want a tuning change rejected if hill-climb capability gets worse.
19. As an operator, I want the rover model to stay suited for graded dirt roads, pads, and light uneven ground.
20. As an operator, I want off-road capability to remain extensible to rougher testing later.
21. As an operator, I want the tower to remain visual-only for now.
22. As an operator, I want the simulator to be a credible substitute for the real rover during operator work.

### Physics Tuning Out Of Scope

- Sensor tower mass modeling
- Camera mast collision
- Extreme rock-crawling targets
- Terrain redesign
- Automatic route scoring or autonomous tuning
- Full real-vehicle parameter identification

---

## CAD And Engineering Asset Requirements

### 8. Support Professional CAD Assets Later

The platform must eventually support:
- CAD drawings and models produced by professionals and corresponding to the real project
- the ability to provide CAD drawings for objects whenever necessary
- separate maintenance of object-level CAD or 3D model files
- inclusion of separately maintained objects in the top-level model

### 9. Modular Asset Workflow

Each major rover or environment object must be manageable independently:
- separate asset ownership
- separate update/replacement of objects
- composition of separately maintained assets into one world
- replacement of rough assets with authoritative assets without redesigning the whole simulator

### 10. Development-To-Authoritative Replacement Path

The platform must support a clean path from early rough or AI-generated assets to later professional CAD-derived assets, without breaking:
- the top-level simulator workflow
- the GCS workflow
- telemetry/replay behavior

---

## Map And Positioning Requirements

### 11. World Map In The GCS

The system must support a world or site map in the Ground Control Station, allowing operators to:
- see rover movement on the map
- relate rover telemetry to position
- use the map in live operation
- use the map in replay visualization

### 12. Position Synchronization

The system must synchronize between:
- rover motion in the simulator
- telemetry data
- map position in the GCS
- future replay visualization

The same logical position model must be usable for both live and replay use cases.

---

## Logging And Replay Requirements

### 13. Logging Is A First-Class Requirement

Logging must be part of the platform design early. The system should log:
- telemetry data
- control traffic
- runtime events
- other important information that passes through the system

Video recording may come later, but the logging and replay architecture must be planned now so video can be added correctly later.

### 14. Logging On Both Rover Side And GCS Side

Logging must be possible in both the rover/simulator side and the GCS side. The system must allow capture from either origin and make that usable in replay.

### 15. Replay Visualization In The GCS

Replay visualization must be available from the GCS, supporting:
- rover movement visualization
- map playback
- telemetry playback
- control/event playback
- synchronized interpretation of captured session data

### 16. Synchronized Replay Timeline

The replay architecture must support synchronization across rover movement, map position, telemetry values, control/event timeline, and future video recording.

### 17. Storage For Logging

Requirements for logging storage:
- structured queryable storage
- session-based recording
- support for replay
- support for synchronization across multiple data types

SQLite is the accepted first implementation choice.

---

## Platform Evolution Requirements

### 18. Customizable Simulation Environment

The new simulation platform must be more customizable than the current environment:
- customizable rover assets
- customizable environment/world assets
- customizable project-specific scenes
- the ability to adapt the simulator to different rover projects

### 19. Do Not Lose Simulation Value While Improving Modularity

The system must become more modular and asset-driven without losing:
- 3D physics usefulness
- rover interaction quality
- simulation environment capability
- practical operator workflow support

### 20. Support Progressive Replacement

The new simulator must coexist with the current one during migration, allowing:
- phased implementation
- phased GCS updates
- phased asset replacement
- eventual full replacement of `3d-env`

without forcing an immediate all-at-once migration.

---

## Documentation Process Requirements

### 21. Plan Reviews Must Be Checked Against Requirements

Whenever the platform plan is reviewed or expanded, it should be checked against this document. The review process should ask:
- which requirements are already covered
- which are only partially covered
- which are still missing
- whether the plan introduced assumptions that are not actually required

### 22. Requirements And Plan Must Stay Separate

This file defines what is required. [design.md](./design.md) defines how the project currently intends to satisfy those requirements. The plan may change more often; the requirements should stay more stable.
