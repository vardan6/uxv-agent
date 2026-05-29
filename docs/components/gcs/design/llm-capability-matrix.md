# LLM Provider Agent Capability Rule

## How GCS currently decides “agent-capable”

In Agent mode, UI/runtime currently treats a provider as tool-capable when either:
- provider capabilities include `tool_calling` or `planner`, or
- provider type is not `ollama` (fallback heuristic in UI).

Reference: [static/ai.js](/mnt/c/Users/vardana/Documents/Proj/remote-rover/gcs_server/static/ai.js)

## Durable Rule

The durable product rule is:

- explicit capability metadata should be the primary signal
- `tool_calling` is sufficient for tool-using agent mode
- `planner` also qualifies a provider for agentic planning paths
- non-`ollama` fallback should be treated as a compatibility heuristic, not a long-term contract
- placeholder model IDs must be treated as unknown until replaced with concrete models and validated
- local models may need explicit conformance checks even when the serving stack advertises tool support

Operational guidance follows directly from that rule: prefer explicit
`tool_calling` metadata, keep `ollama` behind conformance validation unless
verified locally, do not bless placeholder model IDs as agent-capable, and keep
dated context-window comparisons out of durable design docs. The full
provider-by-provider matrix is audit material, not canonical design.
