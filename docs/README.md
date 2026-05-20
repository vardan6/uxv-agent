# Remote Rover Documentation

This directory is the source of truth for project docs. The live surface is intentionally small: two living status docs at the root, fixed three-tier component docs under `components/`, cross-cutting architecture and ADRs under `cross-cutting/`, and historical material under `archive/`.

## Start Here

| Doc | Purpose |
|---|---|
| [current-state.md](./current-state.md) | What is implemented today, what is partial, and what is still missing |
| [roadmap.md](./roadmap.md) | Current forward plan and next implementation slices |
| [cross-cutting/vision.md](./cross-cutting/vision.md) | Project purpose, current value, and long-term AI-assisted direction |
| [cross-cutting/architecture.md](./cross-cutting/architecture.md) | System-wide components, data flow, and MQTT/runtime boundaries |

## Components

| Doc | Purpose |
|---|---|
| [components/README.md](./components/README.md) | One-screen index of documented components and tier completeness |
| [components/ai-agent/README.md](./components/ai-agent/README.md) | AI agent docs: requirements, design, and implementation internals |
| [components/gcs/README.md](./components/gcs/README.md) | GCS docs: operator workflow, runtime model, settings, replay, and AI workspace |
| [components/simulator/README.md](./components/simulator/README.md) | Simulator docs: current `3d-env` baseline and `rover-sim-next` successor path |

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

## Archive

Older plans, superseded designs, review output, and handoff notes live under [archive/](./archive/). Archive content is for traceability, not for the current source of truth.

## Reading Order

For product/status context:

1. [cross-cutting/vision.md](./cross-cutting/vision.md)
2. [current-state.md](./current-state.md)
3. [components/gcs/requirements.md](./components/gcs/requirements.md)
4. [components/ai-agent/requirements.md](./components/ai-agent/requirements.md)
5. [roadmap.md](./roadmap.md)

For implementation context:

1. [cross-cutting/architecture.md](./cross-cutting/architecture.md)
2. [components/gcs/design.md](./components/gcs/design.md)
3. [components/ai-agent/design.md](./components/ai-agent/design.md)
4. [components/simulator/design.md](./components/simulator/design.md)
5. [cross-cutting/decisions/README.md](./cross-cutting/decisions/README.md)
6. [cross-cutting/operations/run-and-config.md](./cross-cutting/operations/run-and-config.md)
