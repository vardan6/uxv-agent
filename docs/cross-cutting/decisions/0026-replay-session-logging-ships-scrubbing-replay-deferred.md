# 0026. Telemetry Session Logging And Frame Scrubbing Ship Now; Deterministic Full-State Replay And Synchronized Video Remain Deferred

Date: 2026-06-13
Status: Accepted

## Context

`3d-env` runs a `ReplayStore` (`replay_store.py`), a `ReplayAnalyticsService`, a
replay API router (`routers/replay.py`), and an operator-facing `/replay` page
(`static/replay.js`). ADR 0014 governs server-side session reference resolution.

The boundary that matters is between *replaying recorded telemetry samples* and
*reconstructing complete deterministic state*. The first works against any
backend; the second requires deterministic snapshots and physics-accurate timing
that `3d-env` cannot provide cleanly. The replay capabilities split along that
line.

## Decision

Replay capabilities are split into two tracks with different defer conditions.

### Track A — Telemetry session logging, analytics, and frame scrubbing (ships now, `3d-env`-era)

`ReplayStore` and its router record per-session telemetry samples, control
events, and runtime events, and expose session timelines, summaries, and
comparison aggregates to operators and AI tools.

The `/replay` page is the operator surface for this data. It supports:

- loading a recorded session and playing back its timeline,
- scrubbing to **any recorded telemetry frame** and seeing the logged rover
  state (position, speed, heading, GPS, camera, power) at that frame,
- inspecting the recorded path and event markers on a Leaflet map.

This is replay of *what was logged*, frame by frame. It does not require
deterministic physics timing or `rover-sim-next`. It is governed by ADR 0014.

### Track B — Deterministic full-state replay, high-fidelity live-map sync, synchronized video (deferred)

These require reconstructing state the telemetry log does not capture, or timing
the log cannot guarantee:

- **deterministic full-state replay** — reconstructing exact simulation state
  (not just logged samples) at arbitrary times, with physics-accurate
  interpolation between frames,
- **sub-second live-map position sync** on the main dashboard,
- **camera-aligned synchronized video review**.

Drifting timestamps and lossy snapshots make these unreliable on `3d-env`. No
partial implementation of Track B lands in `3d-env`-era code. When
`rover-sim-next` is the runtime, open individual implementation ADRs for Track B
features as they are picked up.

## Consequences

- The `ReplayStore` / analytics system and the `/replay` frame-scrubbing surface
  are supported, shipped behavior.
- Operator-experience docs document telemetry-frame scrubbing as shipped and flag
  Track B features as "planned, blocked on `rover-sim-next`".

## Alternatives Considered

- **Keep logging and scrubbing in one deferred bundle.** Rejected: telemetry
  logging and frame scrubbing have immediate observability value and do not
  require deterministic playback timing.
- **Roll back the replay store and scrubbing UI.** Rejected: they provide real
  observability value and frame scrubbing does not require deterministic-quality
  timing.

## Follow-Ups

- Session reference resolution rules: [ADR 0014](./0014-replay-session-resolution-server-side.md).
- Track B features listed in product follow-ups under `docs/components/gcs/design.md` remain blocked on `rover-sim-next` per [ADR 0006](./0006-rover-sim-next-is-next-simulator.md).
