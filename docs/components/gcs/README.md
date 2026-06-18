# GCS

The browser-facing Ground Control Station: dashboard, replay, settings, and the AI workspace that hosts Chat and Agent, plus the remaining backend seams around supervised mission-planning cleanup. The GCS owns browser connections, controller locking, MQTT control publication, telemetry relay, presence signaling, and all backend APIs that power the operator UI.

| Doc | Tier | Purpose |
|---|---|---|
| [requirements.md](./requirements.md) | Requirements | Product target: operator workflow, pages, controls, safety invariants, acceptance criteria |
| [design.md](./design.md) | Design (overview) | Implementation strategy: runtime model, browser workflow, MQTT, AI chat, settings, current limitations. Indexes per-topic files in [`design/`](./design/). |
| [design/*.md](./design/) | Design (per topic) | api-and-runtime, map-widget, llm-capability-matrix. Same stability tier as `design.md`. |
