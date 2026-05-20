# GCS Internals

Topic-level notes on the current GCS implementation. Read [../design.md](../design.md) first for the runtime model and architectural overview.

| File | What it covers |
|---|---|
| [api-and-runtime.md](./api-and-runtime.md) | HTTP/WebSocket route surface, control model, MQTT details, in-memory state, AI chat wiring, intent parsing behavior |
| [map-widget.md](./map-widget.md) | Map widget design: mission overlay rendering, phase plan, backend contracts, coordinate system, review findings |
| [llm-capability-matrix.md](./llm-capability-matrix.md) | Which LLM providers support which agentic capabilities |
| [regressions.md](./regressions.md) | Known control-model regression guards |
