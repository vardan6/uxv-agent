# 0005. Keep `3d-env` As The Current Simulator Runtime

Date: 2026-05-20
Status: Accepted

## Context

Two simulator implementations exist in the repository:

- `3d-env/` — the original Three.js / browser-based simulator that runs today, drives the MQTT contract, and is what every connected component (GCS map widget, AI agent context, mission playback) is currently calibrated against.
- `rover-sim-next/` — a planned next-generation simulator (URDF-based, physics-accurate, headless-capable) that is partially scaffolded but not yet feature-complete or wired into the rest of the system.

Earlier planning documents left it ambiguous which one was "the simulator." This caused churn: some docs assumed `rover-sim-next` was live, others linked to `3d-env`, and review sessions repeatedly relitigated the question.

## Decision

`3d-env/` is the current simulator runtime. It owns the MQTT contract, the live rover-state semantics, and any behavior that other components depend on today. All present-tense documentation about "the simulator" refers to `3d-env`.

`rover-sim-next/` is treated as a forward-looking implementation (see [0006](./0006-rover-sim-next-is-next-simulator.md)) and is not the source of truth for any live behavior until it replaces `3d-env`.

## Consequences

- `components/simulator/design.md` describes `3d-env` behavior in present tense; `rover-sim-next` content lives under planned-work sections and `internals/rover-sim-next-phase-1.md`.
- MQTT contract documentation in `cross-cutting/architecture.md` reflects what `3d-env` publishes today, not what `rover-sim-next` will publish.
- Anyone running the system end-to-end runs `3d-env`. The `rover-sim-next/` README is a quickstart for development on that prototype, not a production runtime.
- When `rover-sim-next` becomes the runtime, this ADR is superseded by a new ADR that records the cutover, not edited in place.

## Alternatives Considered

- **Declare `rover-sim-next` the simulator now and treat `3d-env` as legacy.** Rejected: `rover-sim-next` is not feature-complete and nothing else in the system is wired to it. Documenting it as current would create a documentation/reality gap.
- **Document both as equal peers.** Rejected: forces every reader to decide which one applies, and every cross-link to disambiguate. The single-source-of-truth rule from STYLE.md says pick one.

## Follow-Ups

- ADR for the eventual cutover from `3d-env` to `rover-sim-next` will supersede this one.
- `3d-env/README.md` and `rover-sim-next/README.md` link to `components/simulator/` and make their respective roles explicit.
