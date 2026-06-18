# AI Agent Token Efficiency

## Motivation

Agent turns can become expensive when stable prompt material, full context
snapshots, and verbose tool history are resent on every request. The durable
design goal is to reduce repeated token cost without degrading tool-selection
accuracy or mission-planning safety.

## Primary Cost Drivers

The main recurring cost sources are:

- conversation history replay
- full live-context snapshots even when little changed
- eager detail pre-fetch in chat mode when equivalent tools exist
- verbose tool descriptions and tool-result retransmission
- overlapping tool schemas that force the model to choose among near-duplicate capabilities

## Optimization Priorities

Apply improvements in this order:

- enable provider-side prompt caching for stable prompt prefixes
- prefer context-delta mode over replaying full snapshots every turn
- disable or aggressively trim eager-detail pre-fetch when tools can fetch the same facts on demand
- reduce redundant tool-result replay and repeated failed tool invocations
- consolidate overlapping tools where a single operation-mode tool can call the same deterministic handlers
- shrink tool descriptions only behind evaluation coverage

## Tool-Schema Footprint

The tool registry should optimize for **distinct capabilities**, not maximum
tool count. Many small tools are useful when each tool has a clear, separate
semantic boundary. They become harmful when several names expose the same
service with slightly different filters, because the model must spend context
and selection attention distinguishing near-duplicates.

Current audit findings are maintained in
`docs/cross-cutting/research/tool-loading-context-management.md`. As of the
2026-06-18 audit, the live registry has 50 definitions, while normal agent
source-control filtering exposes fewer names before execution-mode filtering.

Consolidation is allowed when all of these are true:

- the merged tool is a thin dispatcher over existing deterministic handlers
- the first consolidation slice does not change the underlying algorithm or
  returned facts
- the merged schema has a clear `mode`, `operation`, or `action` enum instead
  of an unbounded catch-all argument bag
- source-control, permission, and execution-mode gates remain at least as strict
  as the old tools
- old names remain as compatibility aliases until tests/traces show no behavior
  regression

High-confidence consolidation targets:

- spatial object queries: one `query_map_objects(mode=...)` dispatcher can
  replace direction/kind/nearest wrappers over `SpatialQueryService`
- AI memory queries: one `query_ai_memory(operation=...)` dispatcher can replace
  list/search/message-window tools
- settings queries: one `query_settings(operation=..., section=...)` dispatcher
  can replace summary/section/provider-summary tools
- mission-keyed pause/resume/stop: one
  `control_mission_execution(action=..., mission_id=...)` dispatcher can replace
  the three non-emergency mission control tools

Medium-confidence consolidation target:

- replay access should likely become two tools, for example
  `query_replay_sessions` and `analyze_replay_sessions`, rather than one broad
  replay catch-all. Replay operations have diverse arguments and result shapes.

Do not merge safety-critical or semantically distinct boundaries by default:

- keep `abort` separate from ordinary pause/resume/stop controls
- keep `arm_execution` and `execute_mission` separate because execution-mode
  safety is clearer with explicit names
- keep mission-authoring terminal actions and route-planning tools separate
  until there is dedicated evaluation coverage
- keep `search_project_docs` separate because it is a cited retrieval boundary

## Safety Rules

Optimization work must preserve these constraints:

- accuracy is more important than token reduction for planning and mission workflows
- consolidation must not hide safety-critical actions behind ambiguous generic tools
- tool-description trimming should not ship without an eval harness
- history compaction should keep enough recent detail for correct follow-up reasoning
- caches must invalidate on relevant scene, telemetry, config, or mission changes
- provider-specific caching telemetry should be surfaced so savings are measurable rather than inferred
- tool-count reduction claims must be backed by measured bound-tool counts or provider/request usage, not inventory count alone

## Small-Model Recovery Rule

When a tool failure includes structured recovery hints, weaker models should
prefer the hinted fallback before asking the operator for clarification or
repeating the failed call. This is a robustness rule first, but it also
reduces waste from repeated failed iterations.

## Operational Guidance

Use these practices:

- cache stable prompt prefixes when the provider supports cached input
- prefer full snapshot on session start, then deltas after meaningful state changes
- avoid injecting detail eagerly when an equivalent read-only tool exists
- short-circuit repeated identical tool failures
- cache stable read-only tool results within a session when invalidation is trustworthy
- minimize JSON formatting overhead where readability is not required
