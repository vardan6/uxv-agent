# Remote Rover Documentation

This directory is the source of truth for project docs. The live surface is intentionally small: fixed three-tier component docs under `components/`, cross-cutting architecture and ADRs under `cross-cutting/`, and historical material under `archive/`.

## Start Here

| Doc | Purpose |
|---|---|
| [cross-cutting/vision.md](./cross-cutting/vision.md) | Project purpose, current value, and long-term AI-assisted direction |
| [cross-cutting/architecture.md](./cross-cutting/architecture.md) | System-wide components, data flow, and MQTT/runtime boundaries |
| [components/README.md](./components/README.md) | Entry point to the current component requirements, design, and internals docs |

## Components

| Doc | Purpose |
|---|---|
| [components/README.md](./components/README.md) | One-screen index of documented components and tier completeness |
| [components/ai-agent/README.md](./components/ai-agent/README.md) | AI agent docs: requirements, design, and implementation internals |
| [components/gcs/README.md](./components/gcs/README.md) | GCS docs: operator workflow, runtime model, settings, replay, and AI workspace |
| [components/simulator/README.md](./components/simulator/README.md) | Simulator docs: current `3d-env` baseline and the separate `rover-sim-next` scaffold |

## Cross-Cutting

| Doc | Purpose |
|---|---|
| [cross-cutting/README.md](./cross-cutting/README.md) | Index of system-wide docs |
| [cross-cutting/decisions/README.md](./cross-cutting/decisions/README.md) | ADR index |
| [cross-cutting/operations/README.md](./cross-cutting/operations/README.md) | Runtime and operational docs |
| [cross-cutting/research/README.md](./cross-cutting/research/README.md) | Third-party background and research material |

## Reference

| Doc | Purpose |
|---|---|
| [glossary.md](./glossary.md) | Shared project vocabulary |
| [STYLE.md](./STYLE.md) | Documentation conventions and archive rules |
| [snapshots/README.md](./snapshots/README.md) | Dated point-in-time reports of what a subsystem currently implements — not specs, no authority |

## Archive

Older plans, superseded designs, review output, and handoff notes live under [archive/](./archive/). Archive content is for traceability, not for the current source of truth.

Retired status-hub entry points remain at [current-state.md](./current-state.md) and [roadmap.md](./roadmap.md) as compatibility stubs pointing to canonical docs and archived snapshots.

## Reading Order

For product/status context:

1. [cross-cutting/vision.md](./cross-cutting/vision.md)
2. [components/gcs/requirements.md](./components/gcs/requirements.md)
3. [components/ai-agent/requirements.md](./components/ai-agent/requirements.md)
4. [components/simulator/requirements.md](./components/simulator/requirements.md)
5. [cross-cutting/decisions/README.md](./cross-cutting/decisions/README.md)

For implementation context:

1. [cross-cutting/architecture.md](./cross-cutting/architecture.md)
2. [components/gcs/design.md](./components/gcs/design.md)
3. [components/ai-agent/design.md](./components/ai-agent/design.md)
4. [components/simulator/design.md](./components/simulator/design.md)
5. [cross-cutting/decisions/README.md](./cross-cutting/decisions/README.md)
6. [cross-cutting/operations/run-and-config.md](./cross-cutting/operations/run-and-config.md)
