# Components

This index shows the stakeholder-facing components that use the three-tier documentation model. Each component has fixed `requirements.md`, `design.md`, and `internals/` entrypoints; smaller support modules such as `tts_service` and `config` stay documented in their local READMEs instead of getting full component folders.

| Component | Requirements | Design | Internals | Notes |
|---|---|---|---|---|
| [ai-agent](./ai-agent/README.md) | Complete | Complete | Complete | Includes mission execution and route planning per [ADR 0009](../cross-cutting/decisions/0009-mission-execution-fold-under-ai-agent.md) |
| [gcs](./gcs/README.md) | Complete | Complete | Complete | Includes AI workspace hosting, settings, replay, and operator UI |
| [simulator](./simulator/README.md) | Complete | Complete | Complete | Covers both `3d-env` as current runtime and `rover-sim-next` as successor path |
