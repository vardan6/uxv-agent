# ADR 0029 — Lazy Context Injection (Compact Always-On State + Tool-Loaded Detail)

**Status:** Accepted (revised 2026-06-18 after implementation-plan review)
**Date:** 2026-06-18
**Review:** `docs/cross-cutting/research/2026-06-18-tool-loading-plan-review.md`

> Revision note: the first draft of this ADR said "remove `_tool_calls()`
> pre-injection" and add a system-prompt sentence stating "live rover state,
> scene, and spatial data are not pre-loaded." A code review found that wording
> would have produced a **self-contradicting prompt**: the implementation still
> injects rover/runtime/mission/scene through `context_snapshot.prompt`
> (`AIContextService.build_compact_context` → `_format_context_block`), so the
> model would have been *told* state was absent while still *receiving* it. This
> revision scopes the decision to what the code actually does and what is safe to
> change without a quality regression.

## Context

On every Agent-mode request, `chat_service.py` builds two overlapping copies of
live state:

1. **Synthetic tool-call preamble** — `_tool_calls(context_snapshot)` fabricates
   tool-call records for `get_current_rover_state` and `get_scene_summary` (the
   only two providers in its map that resolve in Agent mode) and injects them as
   if the model had already called those tools in turn 0. These render as the
   "Context used" section in the chat UI.
2. **Compact context block** — `AIContextService.build_compact_context` always
   assembles `rover`, `runtime`, `mission`, and `scene` and serializes them
   through `_format_context_block` as a "Live GCS current context" system
   message (`context_snapshot.prompt`), appended to every agent prompt by
   `_prompt_for_mode` → `_context_prompt`.

**Rover and scene are therefore injected twice per agent turn** — once as
synthetic tool calls, once inside the compact JSON block. The duplicate carries
no information the block does not already carry.

Separately, of the four always-on sections, `runtime` (broker / controller /
video / simulation / map config) is rarely the answer to an operator question,
yet it is sent on every turn.

### The trade-off rule this ADR is built on

Lazy loading is **not** universally good. The honest rule:

> **Lazy loading wins when data is usually *not* needed. It loses when data is
> usually needed** — you pay an extra LLM round-trip *and* you still send the
> data (now as a tool result with schema + framing overhead), just one turn
> later. For data needed by most turns, lazy loading is a net token *and* latency
> loss.

For an operator-facing rover agent, **rover pose, mission state, and scene
summary are usually needed**; runtime/broker config, replay history, telemetry
samples, settings, LLM config, and chat history are usually not. The codebase
already lazy-loads the query-triggered details correctly (`eager_detail_mode =
not agent_mode` in `context_service.py` — spatial/replay details are not
preloaded in Agent mode). This ADR finishes that classification for the four
always-on sections.

## Decision

Scope the change to the no-regression, mostly quality-positive set ("Tier 1"):

1. **Remove the duplicate.** Drop `_tool_calls()` synthetic pre-injection in
   Agent mode. Rover and scene remain available once, in the compact context
   block — nothing the model needs is lost.
2. **Lazy-load `runtime`.** Stop assembling `runtime` into the always-on compact
   block; expose it through the existing `get_runtime_context` tool so the agent
   fetches broker/sim/map config only on the rare turn that needs it.
3. **Keep compact rover, mission, and scene summary always-on.** These are
   needed by most operator turns; lazy-loading them would add a round-trip to the
   majority of queries (see trade-off rule). Detail (map objects, replay paths,
   etc.) stays tool-loaded as it already is.
4. **Compact the rendering.** Replace the `sort_keys` JSON dump in
   `_format_context_block` with a compact text rendering of the same facts; JSON
   keys and punctuation are pure overhead with no information value.

### Prompt changes (must ship in the same commit)

- **`AGENT_SYSTEM_PROMPT`** — add an accurate sentence:
  *"You are given a compact summary of current rover pose, mission state, and
  scene as authoritative facts. Detailed map objects, replay history, telemetry
  samples, settings, and runtime/broker config are not pre-loaded — call the
  matching read-only tool when the operator's question needs them."*
  (Do **not** claim rover/scene are absent — they are present.)
- **`_prompt_for_mode`** — make the agent opening conditional so an empty
  tool-call list no longer reads "use the results below as current facts." When
  there is no synthetic preamble, the compact context block speaks for itself.

## Consequences

**Positive:**

- Removes a per-turn duplicate of rover+scene at zero quality cost.
- Drops always-on `runtime` config (rarely needed) from every turn.
- Compact rendering shrinks the same facts further.
- Agent trace is honest: state the agent actively fetches appears as real tool
  cards, not fabricated turn-0 history.
- Aligns with requirements §Primary Product Requirement (gradual, lazy
  discovery) for the surfaces where lazy loading is actually a win.

**Quality risk:** **None expected for Tier 1.** Rover/mission/scene — the
surfaces most queries depend on — remain in context. The only newly-lazy surface
is `runtime` config, which is almost never the answer; on the rare turn that
needs it, the agent pays one tool round-trip. More aggressive lazy loading
(removing rover/scene/mission entirely) is **explicitly rejected here** and
deferred to eval-gated Tier 3 work (see roadmap "Agent Tool-Schema
Optimization"), because it would regress implicit-state queries such as "plan a
mission for me."

**UI consequence:** the "Context used" section (synthetic
`prompt_context_tool_calls`) disappears, because the preamble it rendered is
removed. The compact context block still reaches the model; if a disclosure of
preloaded context is wanted, surface the compact block as a single preamble node
in the unified agent flow rather than as fake tool cards. See
`design.md` §Agent Chat UI.

**Accepted constraints:**

- The smalltalk bypass (`_is_trivial_agent_smalltalk`) is unaffected.
- The two prompt changes above are **required** in the same commit.
- The lazy loaders (`lazy_load_replay`, `lazy_load_ai_memory`,
  `lazy_load_settings`, `lazy_load_sensor`) are a separate concept — they defer
  data payload, not schema injection, and are currently not in the agent
  allowlist. Their stale/expose decision is tracked in
  `tool-loading-context-management.md`, not here.

## HITL verification

Before marking the slice complete, manually confirm these five prompts produce
equivalent-or-better answers than the pre-change baseline (covering the risk
surfaces named in the trade-off rule):

1. **Rover-state:** "Where is the rover and what's the battery level?" — must use
   the compact rover summary (no regression; no extra tool call expected).
2. **Spatial:** "What's the nearest boulder?" — must call a spatial tool (detail
   was already tool-loaded; confirm no regression).
3. **Runtime/config (newly lazy):** "What MQTT broker and port is configured?" —
   must now call `get_runtime_context`; confirm it does so instead of failing.
4. **Mission-authoring:** "Plan a route around the rock cluster." — must produce
   a mission via a terminal mission-creation tool (implicit-state path).
5. **Meta/project:** "What is this project about?" — should answer from
   `project_docs` RAG with citations, not from removed context.

## Rejected alternatives

**Remove all preloaded live state (full lazy).** Rejected for now: rover, scene,
and mission are needed by most operator turns, so removing them adds a round-trip
to the majority of queries and risks implicit-state failures. Revisit only as
eval-gated Tier 3 work, after the measurement harness and golden-question eval
set exist.

**Keep the synthetic `_tool_calls()` preamble, surface it nicely in the UI.**
Rejected: it is a duplicate of the compact block; the fix is to delete the copy,
not to render it better.

**Add the "state is not pre-loaded" sentence as originally drafted.** Rejected:
it contradicts the implementation (state *is* pre-loaded in compact form) and
would mislead the model into redundant tool calls.
