# rover-sim-next Phase 1 Checklist

## Purpose

Status snapshot date: 2026-05-08.

This checklist turns the `rover-sim-next` plan into a concrete first implementation scope.

Phase 1 goal:
- make `rover-sim-next` a working simulator backend
- keep `3d-env` working during transition
- work with the existing `gcs_server` contract
- use development assets now without blocking later CAD-driven replacement

This checklist is intentionally limited to the first usable milestone.
It does not try to complete the full long-term simulator platform.

## Phase 1 Acceptance Criteria

Phase 1 is complete when all of the following are true:

- `rover-sim-next` launches as a real simulator process
- one rover can be driven from the current GCS without a GCS-side protocol rewrite
- the simulator publishes telemetry on the existing MQTT telemetry topic
- the telemetry contains the minimum fields already expected by the GCS
- the GCS can display rover movement and status using `rover-sim-next`
- the simulator provides a first compatible camera path or a clearly defined temporary equivalent
- backend identity is explicit as `rover-sim-next`
- `3d-env` still remains runnable as the old backend

## Current File/Module Baseline

Existing scaffold modules:
- `rover-sim-next/package.xml`
- `rover-sim-next/CMakeLists.txt`
- `rover-sim-next/launch/sim_bridge.launch.py`
- `rover-sim-next/config/rover_sim_next.example.yaml`
- `rover-sim-next/rover_sim_next/mqtt_bridge.py`
- `rover-sim-next/urdf/`
- `rover-sim-next/worlds/`

Current GCS contract references:
- `config/common.example.json`
- `gcs_server/config.py`
- `gcs_server/telemetry.py`

## Work Packages

### 1. Runtime And Launch

Files:
- `rover-sim-next/package.xml`
- `rover-sim-next/CMakeLists.txt`
- `rover-sim-next/launch/sim_bridge.launch.py`
- `rover-sim-next/README.md`

Required work:
- make the package install and run as a real ROS 2 package
- replace the placeholder launch flow with a launch that starts Gazebo and the bridge nodes
- define launch arguments for config path, world path, headless mode, and robot pose
- document the exact command used to run the first simulator milestone

Done when:
- the package can be launched with one command
- launch arguments are explicit and documented
- the launch path works for both local GUI use and basic headless execution

### 2. Config Contract

Files:
- `rover-sim-next/config/rover_sim_next.example.yaml`
- `rover-sim-next/rover_sim_next/mqtt_bridge.py`

Required work:
- expand the config file from a stub into the actual simulator runtime contract
- include broker host, broker port, topics, telemetry rate, camera settings, site origin, and backend version
- define rover spawn position and heading
- define world file path and rover model path
- define local coordinate frame and temporary GPS conversion settings

Suggested config sections:
- `simulation`
- `mqtt`
- `site`
- `vehicle`
- `world`
- `camera`

Done when:
- the simulator can start entirely from config
- the config names map clearly onto the existing GCS expectations
- site and coordinate settings are explicit, not implicit

### 3. Rover Model

Files:
- `rover-sim-next/urdf/README.md`
- new files under `rover-sim-next/urdf/`

Required work:
- create the first drivable rover description
- include chassis, wheels, collision geometry, inertial properties, and wheel joints
- keep the first model simple and physically stable rather than visually detailed
- separate visual and collision intent even if both use simple geometry at first

Recommended Phase 1 approach:
- start with primitive geometry or very simple generated meshes
- use placeholder masses and inertias that are physically coherent
- avoid over-modeling suspension and articulation in the first pass

Done when:
- the rover can spawn reliably
- the rover does not immediately explode or drift under physics
- wheel-driven motion can be controlled through the bridge layer

### 4. World Model

Files:
- `rover-sim-next/worlds/README.md`
- new files under `rover-sim-next/worlds/`

Required work:
- create one first development world
- keep it simple: ground plane or simple terrain, a few obstacles, and clear drive space
- preserve the idea of site identity and map origin from the beginning
- keep world composition modular so later objects can be swapped independently

Recommended Phase 1 approach:
- one small site first
- deterministic spawn point
- no heavy asset complexity yet

Done when:
- the world loads reliably
- rover spawn is deterministic
- the world is suitable for basic drive, telemetry, and camera tests

### 5. Simulator Control Path

Files:
- `rover-sim-next/rover_sim_next/mqtt_bridge.py`
- likely new runtime modules under `rover-sim-next/rover_sim_next/`

Required work:
- subscribe to the existing control topic
- parse current GCS control payloads without changing the GCS protocol
- convert control commands into rover actuation inside the simulator
- implement safe defaults when no control is present
- define the first control update loop clearly

Implementation note:
- do not redesign the operator control payload in Phase 1
- adapt `rover-sim-next` to the current GCS contract first

Done when:
- the rover responds to current browser control inputs through the existing GCS
- steering and throttle/brake behavior are stable enough for manual driving

### 6. Telemetry Path

Files:
- `rover-sim-next/rover_sim_next/mqtt_bridge.py`
- likely new telemetry helper modules under `rover-sim-next/rover_sim_next/`
- contract reference: `gcs_server/telemetry.py`

Required work:
- publish telemetry on the current state topic
- include the minimum fields expected by the GCS
- publish backend identity as `rover-sim-next`
- include local position, GPS compatibility fields, heading, speed, camera mode, and power placeholders

Minimum telemetry shape to preserve:
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

Done when:
- the existing GCS dashboard can display rover state from `rover-sim-next`
- telemetry cadence is stable enough for the current UI
- no GCS-side parser change is required for the basic telemetry path

### 7. Coordinate And Map Foundation

Files:
- `rover-sim-next/config/rover_sim_next.example.yaml`
- likely new helper module such as `rover-sim-next/rover_sim_next/coordinates.py`

Required work:
- formalize local frame semantics now
- define site origin explicitly in config
- provide deterministic local-to-map conversion
- keep pseudo-GPS compatibility only as a transition layer

Recommended Phase 1 rule:
- use an ENU-style local frame
- make the site origin configurable
- keep the transform implementation simple and documented

Done when:
- rover motion in local coordinates deterministically maps to GPS-compatible values
- the same foundation can later support both live map and replay map without redesign

### 8. Camera Compatibility

Files:
- likely new camera module under `rover-sim-next/rover_sim_next/`
- `rover-sim-next/config/rover_sim_next.example.yaml`

Required work:
- provide enough camera behavior to keep the current GCS workflow usable
- decide whether the first implementation publishes image frames through the existing practical path or uses a temporary adapter
- keep the camera contract explicit in config

Phase 1 decision rule:
- choose the simplest path that preserves end-to-end usability with the current GCS
- do not block simulator bring-up on final media architecture decisions

Done when:
- the GCS can show a usable simulated camera feed or a clearly defined compatible interim stream

### 9. GCS Compatibility Validation

Files:
- `config/common.example.json`
- `gcs_server/app.py`
- `gcs_server/mqtt_service.py`
- `gcs_server/static/app.js`

Required work:
- verify that backend switching still works cleanly
- verify that the GCS can run against either `3d-env` or `rover-sim-next`
- verify that no new simulator-only assumptions leak into the current `3d-env` path

Done when:
- `3d-env` still works
- `rover-sim-next` also works with the same GCS entrypoint
- the operator can tell which backend is active

### 10. Development Asset Rules

Files:
- `rover-sim-next/README.md`
- `rover-sim-next/urdf/README.md`
- `rover-sim-next/worlds/README.md`

Required work:
- document that early rover and world assets may be prompt-generated or quickly modeled
- define them as development assets, not engineering source-of-truth
- keep the folder structure ready for later authoritative replacements

Done when:
- the first implementation can move fast using rough assets
- later professional assets can replace those files without changing the GCS contract

## Suggested Module Split

The scaffold should not remain a single placeholder bridge file.
The first practical split should be:

- `rover_sim_next/config.py`
  Loads and validates simulator config.
- `rover_sim_next/mqtt_bridge.py`
  Owns MQTT connectivity and topic I/O.
- `rover_sim_next/telemetry.py`
  Builds GCS-compatible telemetry payloads.
- `rover_sim_next/coordinates.py`
  Converts local simulator pose into GPS-compatible values.
- `rover_sim_next/control.py`
  Translates MQTT control payloads into simulator actuation commands.
- `rover_sim_next/camera.py`
  Handles the first compatible camera publishing path.
- `rover_sim_next/runtime.py`
  Coordinates startup, shutdown, timers, and simulator integration.

This split is small enough for Phase 1 and avoids packing unrelated logic into one file.

## Suggested Delivery Sequence

1. Make launch and config real.
2. Add first rover model and first world.
3. Implement control bridge.
4. Implement telemetry publisher.
5. Add coordinate conversion.
6. Add camera compatibility.
7. Validate against the current GCS.
8. Document exact run and test steps.

## Explicitly Deferred

These items remain required by the broader plan, but should not block Phase 1:

- simulator-side replay logging
- richer GCS live map page work
- synchronized replay/video playback
- CAD-derived authoritative asset import
- advanced environment modularity beyond the first practical world structure
- high-fidelity rover dynamics beyond the first stable controllable model

## Exit Decision For Phase 1

When Phase 1 is complete, the next planning decision should be:

- either improve the rover/world realism and asset pipeline first
- or add live map plus simulator-side logging next

That decision should be made only after `rover-sim-next` is actually drivable from the current GCS.
