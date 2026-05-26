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

## Optimization Priorities

Apply improvements in this order:

- enable provider-side prompt caching for stable prompt prefixes
- prefer context-delta mode over replaying full snapshots every turn
- disable or aggressively trim eager-detail pre-fetch when tools can fetch the same facts on demand
- reduce redundant tool-result replay and repeated failed tool invocations
- shrink tool descriptions only behind evaluation coverage

## Safety Rules

Optimization work must preserve these constraints:

- accuracy is more important than token reduction for planning and mission workflows
- tool-description trimming should not ship without an eval harness
- history compaction should keep enough recent detail for correct follow-up reasoning
- caches must invalidate on relevant scene, telemetry, config, or mission changes
- provider-specific caching telemetry should be surfaced so savings are measurable rather than inferred

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
