# Components

This index shows the stakeholder-facing components that use the two-tier documentation model. Each component has fixed `requirements.md` and `design.md` entrypoints; smaller support modules such as `tts_service` and `config` stay documented in their local READMEs instead of getting full component folders. (Until 2026-05-26 there was also a third `internals/` tier; its content has been folded into `design.md` per the supersession note in ADR 0010.)

| Component | Requirements | Design | Notes |
|---|---|---|---|
| [ai-agent](./ai-agent/README.md) | Complete | Complete | Includes mission execution and route planning per [ADR 0009](../cross-cutting/decisions/0009-mission-execution-fold-under-ai-agent.md) |
| [gcs](./gcs/README.md) | Complete | Complete | Includes AI workspace hosting, settings, replay, and operator UI |
| [simulator](./simulator/README.md) | Complete | Complete | Covers `3d-env` as the current runtime and `rover-sim-next` as a scaffolded side path |
