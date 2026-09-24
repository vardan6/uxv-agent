# Components

This index shows the stakeholder-facing components that use the two-tier
documentation model. Each component has fixed `requirements.md` and `design.md`
entrypoints; smaller support modules such as `tts` and `config` stay
documented in their local READMEs instead of getting full component folders. A
retired third `internals/` tier was folded into `design.md`.

Requirements and design documents are durable specifications. They describe
product behavior, architecture, invariants, interfaces, and rationale; they do
not carry planning slice identifiers, delivery status, completion dates,
session handoffs, or next-work instructions. Those belong in root `roadmap.md`,
`activeContext.md`, and `progress.md`; dated verification belongs in
`docs/reviews/` or `docs/snapshots/`.

| Component | Notes |
|---|---|
| [ai-agent](./ai-agent/README.md) | Includes mission execution and route planning per [ADR 0009](../cross-cutting/decisions/0009-mission-execution-fold-under-ai-agent.md) |
| [gcs](./gcs/README.md) | Includes AI workspace hosting, settings, replay, and operator UI |
| [simulator](./simulator/README.md) | Covers the simulator architecture and successor boundary |
