# AI Agent Token Efficiency

Related docs:

- [Tool Contract Standard](./tool-contract.md)

## Motivation

Agent turns can become expensive when stable prompt material, full context
snapshots, and verbose tool history are resent on every request. The durable
design goal is to reduce repeated token cost without degrading tool-selection
accuracy or mission-planning safety.

## The Lazy-Loading Trade-off Rule

Lazy loading is **not** universally good. The governing rule for every
context/tool decision:

> **Lazy loading wins when data is usually *not* needed. It loses when data is
> usually needed** — you pay an extra LLM round-trip *and* you still send the data
> (now as a tool result with schema + framing overhead), just one turn later.

Consequence: classify each always-on surface by need-frequency and lazy-load only
the rarely-needed ones.

- Usually needed each turn (keep always-on, compact): rover pose, mission state,
  scene summary, run mode/permissions, manifest, safety boundaries.
- Usually not needed (lazy via tools): runtime/broker/sim/map config, detailed map
  objects, replay paths/metrics, telemetry samples, settings sections, chat
  history, sensor detail, RAG chunks.

The same rule applies to **tool schemas**: prune/defer schemas the current turn is
unlikely to use; never defer the schemas most turns need. See ADR 0029 for the
context application and the roadmap "Agent Tool-Schema Optimization" tiers for the
schema application.

## Measure Before Cutting

Token-savings claims must be backed by the measurement harness, not estimates.
Measure all surfaces separately: provider tool-schema payload, the tool-name list
prompt, the data-surface manifest prompt, and the compact context block. The
compact context block uses a 24,000-char default budget, so it is materially
larger than the inputs to early estimates — never optimize it (or anything) on
assumed sizes.

**Harness:** `backend/tools/measure_agent_surfaces.py`  
Run from repo root: `PYTHONPATH=backend:. .venv/bin/python -m tools.measure_agent_surfaces`

### Measured baseline (2026-06-18, post-ADR-0029-Tier-1)

"default" = `normalize_source_controls({})` → replay_reports + project_docs on.  
"all-on" = all five optional source controls enabled.

| Surface | default | all-on |
|---------|---------|--------|
| Tools bound | 31 | 38 |
| Provider tool-schema JSON | 54,921 B (~13,730 tok) | 63,616 B (~15,904 tok) |
| Tool-name list prompt | 770 chars (~192 tok) | 922 chars (~230 tok) |
| Data-surface manifest prompt | 703 chars (~175 tok) | 900 chars (~225 tok) |
| Context block budget | 24,000 chars (~6,000 tok) | same |

### Measured post-Tier-1 (2026-06-18, spatial + metadata + replay dispatchers)

All Tier 1 binding-reduction slices shipped: spatial (−5), AI memory/settings (−4), replay (−8).

| Surface | default | all-on |
|---------|---------|--------|
| Tools bound | 18 | 21 |
| Provider tool-schema JSON | 38,174 B (~9,543 tok) | 42,465 B (~10,616 tok) |
| Tool-name list prompt | 440 chars (~110 tok) | 492 chars (~123 tok) |
| Data-surface manifest prompt | 354 chars (~88 tok) | 451 chars (~112 tok) |
| Context block budget | 24,000 chars (~6,000 tok) | same |

**Total reduction from baseline:** −16,747 B default (−30.5%), −21,151 B all-on (−33.3%).
Schema bytes still dominate. Context block budget is a cap, not a constant; actual prompt
size for a given request can be far smaller. Re-run the harness after each further change.

### Measured post-dispatcher-contract follow-up (2026-06-18, local review pass)

The branch follow-up that restored mandatory dispatcher contracts raised the
default schema from `38,174 B` to `41,706 B` (about `+9%`, still `−24%` vs the
`54,921 B` baseline). This is the correct trade for contract completeness, but
it also exposed a new optimization target: **contract projection verbosity**.

Important split:

- keep full dispatcher contract metadata
- do not assume the full contract must be serialized verbatim into every
  model-facing tool description

Local audit of the five new dispatcher contracts (`control_mission`,
`query_replay_sessions`, `analyze_replay_sessions`, `query_ai_memory`,
`query_settings`) showed roughly `3236` added chars of always-on runtime text,
with the largest contributors in the appended contract block being:

- `inputs`: `1459` chars
- `returns`: `1048` chars
- `upstream_from_tools`: `507` chars

This makes compact runtime projection the next low-risk place to cut tokens
without discarding the contracts themselves.

## Contract Projection Rule

Treat contract storage and model-facing contract projection as separate
surfaces.

- `TOOL_CONTRACTS` remains the durable source of truth.
- The runtime description should include only the minimum contract detail the
  model needs to select the tool and form valid arguments.
- `/capabilities` or other operator/debug surfaces may remain more verbose.

Recommended compression order:

1. keep base description + operation/mode/action values
2. keep required arguments and compact return-shape summary
3. trim or omit always-on `upstream_from_tools` — **done** (2026-06-24): omitted
   from `_tool_runtime_description`, retained in `TOOL_CONTRACTS`/`/capabilities`
4. trim or omit always-on `next_tools` — **done** (2026-06-24, same slice)
5. compress verbose `returns` branch maps into top-level summaries when the
   branch detail is already clear elsewhere — still gated on the live
   tool-chaining checklist confirmation for steps 3–4

Do **not** "optimize" by removing contracts entirely. For dispatcher tools that
would trade token savings for weaker discoverability and higher invalid-call
risk.


## Primary Cost Drivers

The main recurring cost sources are:

- conversation history replay
- full live-context snapshots even when little changed
- **duplicated** state injection — historically rover/scene were injected both as
  a synthetic turn-0 tool-call preamble and inside the compact context block
  (removed in ADR 0029)
- always-on injection of rarely-needed surfaces (e.g. runtime/broker config)
- eager detail pre-fetch in chat mode when equivalent tools exist
- verbose tool descriptions and tool-result retransmission
- full-contract verbosity repeated in model-facing tool descriptions
- overlapping tool schemas that force the model to choose among near-duplicate capabilities

## Optimization Priorities

Apply improvements in this order:

- measure first (harness over the surfaces above); never cut on estimates
- remove duplicated injection and always-on rarely-needed surfaces (lazy-loading
  rule), keeping usually-needed state always-on and compact
- consolidate overlapping tool schemas where a single operation-mode tool can call
  the same deterministic handlers (bind-new and unbind-old in the same slice so the
  bound catalog never temporarily grows)
- preserve full tool contracts, but compress the **model-facing projection** of
  those contracts before attempting higher-risk pruning
- prefer context-delta mode over replaying full snapshots every turn
- disable or aggressively trim eager-detail pre-fetch when tools can fetch the same facts on demand
- reduce redundant tool-result replay and repeated failed tool invocations
- audit any remaining **uncached** fallback/chat paths and surface cache-hit
  telemetry — provider prompt caching is already enabled for the agent system
  prompt (`agent_loop.py` sets Anthropic `cache_control`; OpenAI auto-caches), so
  the remaining work is verification and measurement, not adding caching.
  Cache counters are now normalized by `ai/usage_telemetry.py` (promotes
  `cache_read_input_tokens` / `cache_creation_input_tokens` from LangChain's
  nested `input_token_details` to top-level keys in stored message meta);
  live-provider confirmation of an actual cache hit is the remaining step.
- shrink tool descriptions or per-intent prune the visible catalog only behind
  evaluation coverage, because both change the model's visible capability surface

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
- mission-keyed pause/resume/stop: `control_mission(action=..., mission_id=...)`
  dispatcher replaces the three non-emergency mission control tools ✓ done

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
