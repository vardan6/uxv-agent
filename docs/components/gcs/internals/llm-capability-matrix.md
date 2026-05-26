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

## Operational Guidance

- Prefer provider entries that declare `tool_calling` directly instead of relying on fallback inference.
- Keep `ollama` models behind tool-call conformance validation unless they have been verified in this environment.
- Do not rank placeholder or vendor-agnostic model IDs as agent-capable without concrete validation.
- Keep context-window comparisons out of durable design docs; they are dated operational snapshots.

The full provider-by-provider matrix is archival audit material rather than durable system design.
