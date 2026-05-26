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
