# GCS

The browser-facing Ground Control Station: dashboard, replay, settings, and the AI workspace that hosts Chat, Agent, intent-test, and planning-shell modes. The GCS owns browser connections, controller locking, MQTT control publication, telemetry relay, presence signaling, and all backend APIs that power the operator UI.

| Doc | Tier | Purpose |
|---|---|---|
| [requirements.md](./requirements.md) | Requirements | Product target: operator workflow, pages, controls, safety invariants, acceptance criteria |
| [design.md](./design.md) | Design | Implementation strategy: runtime model, browser workflow, MQTT, AI chat, settings, current limitations. Topic-level internals (api-and-runtime, map-widget, llm-capability-matrix) are folded in at the end of this file as of 2026-05-26. |
