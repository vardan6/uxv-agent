# Simulator Technical Details

## Runtime Structure

The simulator is a Panda3D application centered on `simulator/main.py`.

Important responsibilities inside the runtime:
- build terrain and scene geometry from `config/terrain_scene.v1.json`
- create rover physics objects
- merge local and MQTT control input
- generate telemetry payloads
- publish telemetry and camera frames through the MQTT bridge
- expose menu and settings behavior

## Terrain Scene Data

Current terrain and static scene data are manifest-driven.

Runtime source:
- `config/terrain_scene.v1.json`

Generator and validation:
- `tools/generate_terrain_scene.py`
- `tools/validate_terrain_scene.py`

`simulator/terrain.py` reads the explicit heightfield and road definitions. `simulator/main.py` reads the explicit object list and creates boxes, ellipsoid rocks, compound trees, collision proxies, and the configured spawn point.

The legacy compact file `config/terrain_scene.json` is only generator input during this transition. Runtime code should not use it directly.

## MQTT Integration

### Control Subscription

The simulator subscribes to:
- `{topic_prefix}/{control_topic}`

It accepts control frames with button-based and optional analog fields, then applies them according to the configured control mode and failsafe timeout.

### Telemetry Publication

The simulator publishes telemetry payloads to:
- `{topic_prefix}/{state_topic}`

The payload currently includes:
- timestamp
- position
- deterministic virtual GPS derived from the terrain georeference
- orientation
- IMU placeholders and angular velocity
- barometer altitude
- speed and velocity
- physics debug state (`visible`, wheel contacts, throttle, steering)
- manual tuning-route reminder metadata used by the HUD
- camera mode metadata
- power placeholder values

### Camera Publication

The simulator publishes JPEG bytes to:
- `{topic_prefix}/{camera_topic}`

Current source:
- POV offscreen buffer capture

### GCS Presence Tracking

The simulator subscribes to:
- `{topic_prefix}/{gcs_presence_topic}/+`

It stores presence by `gcs_id` and considers a GCS active only when:
- the payload says `active: true`
- the payload contains a recent timestamp
- the timestamp age is within `gcs_presence_timeout_ms`

## Publish Gating Logic

The simulator uses one gate for all outbound MQTT publishing.

Current gate behavior:
- state telemetry publish is blocked when policy does not allow it
- camera frame publish is blocked when policy does not allow it

This matters because disabling only state telemetry would still leak bandwidth through camera frames.

## UI Surface

Current operator-visible UI related to MQTT includes:
- bottom status bar with MQTT state and telemetry policy/effective state
- menu item `Settings -> Telemetry Policy`
- MQTT settings dialog fields for:
  - broker host and port
  - topics
  - rates
  - control mode
  - telemetry policy
  - GCS presence topic
  - GCS presence timeout

Current operator-visible UI related to rover tuning includes:
- a physics debug HUD line for pitch, roll, wheel contacts, throttle, and steering
- a manual test-route HUD reminder: straight bump, uphill climb, side-slope traverse, downhill turn
- a condensed pass/fail reminder in the HUD: climb not worse than baseline, one main rebound, slide before roll, no uncontrolled washout

## Rover Runtime Baseline

The accepted rover baseline in `simulator/rover.py` now combines geometry and dynamics decisions from the completed tuning loop.

Visual/geometry baseline:
- larger wheel radius than the original baseline
- rendered body lowered through derived visual-offset variables rather than ad hoc node edits
- visual-only tower with thicker post/base/head and reduced height relative to the first tower pass
- raised POV camera carried by the tower-oriented rover silhouette

Dynamics baseline:
- suspension tuned for medium travel with quicker settling after drop or bump
- speed-dependent drift allowed through a modest reduction in friction and speed-based planting force
- side-slope stability improved through lower roll influence and stronger rotational damping
- steering input smoothed with a steering-response ramp so the front wheels do not snap instantly to full angle

Important boundary:
- the tower remains visual-only in this phase; it does not contribute mass, inertia, or collision
- the current baseline is accepted for graded dirt roads, pads, and light uneven ground, not for extreme rock crawling

## Current Technical Limitations

- camera transport is still MQTT JPEG publishing
- there is no dedicated simulator-side diagnostics screen for presence entries yet
- shared runtime config is practical but still broad
- power values are placeholders rather than a modeled vehicle power system
- the manual route is currently an overlay reminder, not an in-world marked course or automatic checkpoint detector

## Current Testing Reality

The current codebase supports real runtime testing, but the project still depends heavily on manual end-to-end validation for:
- broker reconnect behavior
- stale presence behavior
- video freshness
- cross-platform launcher behavior
