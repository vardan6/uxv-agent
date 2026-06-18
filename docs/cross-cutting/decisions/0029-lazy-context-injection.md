# ADR 0029 — Lazy Context Injection

**Status:** Accepted  
**Date:** 2026-06-18

## Context

When an Agent-mode request is received, `chat_service.py` calls `_tool_calls(context_snapshot)` before the agent loop starts. This function pre-injects the results of up to nine live-state tools (`get_current_rover_state`, `get_scene_summary`, `query_objects_in_front`, `query_objects_near`, `query_objects_by_kind`, `get_current_replay_summary`, `get_recent_telemetry`, `resolve_replay_sessions`, `get_recent_ai_chat_history`) directly into the system prompt as synthetic tool-call history. The model receives these results as if it had already called those tools in turn 0.

This was designed to ensure the model always has rover state available without having to call a tool. The side effects are:

- The model cannot decide whether it needs the state — it always receives it.
- Pre-injected results show up as a separate "Context used" section in the chat UI, disconnected from the agent's actual reasoning trace.
- Token cost is incurred on every agent turn regardless of query intent.
- The pattern contradicts the product requirement that the agent "discover information gradually and lazily instead of front-loading large context."
- The existing design note ("do not optimize away this baseline by default") was a guard against accidental or casual removal — this ADR is the explicit scoping that guard was designed to require.

## Decision

Remove the server-side `_tool_calls()` pre-injection. The agent calls `get_current_rover_state`, `get_scene_summary`, and any other live-state tools only when it decides it needs them during the reasoning loop.

The "Context used" UI section disappears as a consequence — those calls will appear as normal tool cards inside their iteration node in the unified agent flow (ADR/design companion: `design.md` §Agent Chat UI).

## Consequences

**Positive:**

- Agent decisions are visible and inspectable — every state access appears as a tool call in the run trace.
- Token cost is incurred only when state is actually needed.
- Fully aligns with requirements §Primary Product Requirement: lazy, gradual discovery.
- "Context used" section removed from UI; the flow structure is cleaner.

**Risk — quality degradation: LOW-MEDIUM without mitigations, NEAR-ZERO with them.**

Three scenarios where the model might fail to call a state tool without pre-injection:

1. **Implicit state dependency** — "Plan a mission for me." Nothing in the query triggers a tool call keyword; the model may draft from conversation history instead of fetching fresh rover state.
2. **Stale history reuse** — operator asked "where is the rover?" four messages ago; model answers a follow-up from that cached result. This scenario carries identical risk with pre-injection (the snapshot is also stale by response time) and is largely correct behaviour.
3. **Misleading empty-list prompt** — current `_prompt_for_mode` opens with "Use the read-only tool/context results below as current facts." When the injected list is empty the model may interpret this as "no state is available, proceed without tools."

Both Scenario 1 and 3 are fully closed by two changes shipped in the same commit as the `_tool_calls()` removal:

- **`AGENT_SYSTEM_PROMPT`**: add one sentence — "Live rover state, scene, and spatial data are not pre-loaded — call the state tools when the operator's question depends on current rover position, heading, map objects, or scene details."
- **`_prompt_for_mode`**: make the opening conditional — when `tool_calls` is empty emit "No rover state has been pre-loaded — call state tools when needed" instead of "Use the results below as current facts."

The existing tool descriptions already carry strong keyword triggers for explicit queries (`get_current_rover_state` lists "pose, heading, battery, speed"; spatial tools list "ahead, in front, nearby" etc.), so explicit rover-state questions carry near-zero risk regardless.

**Accepted constraints:**

- The smalltalk bypass (`_is_trivial_agent_smalltalk`) is unaffected.
- The two prompt changes above are **required** in the same commit — this slice is not considered complete without them.
- The lazy loaders (`lazy_load_replay`, `lazy_load_ai_memory`, `lazy_load_settings`, `lazy_load_sensor`) are a separate concept — they defer data payload, not schema injection. This ADR does not change their behavior; see `tool-loading-context-management.md` for their current status.

## Rejected alternatives

**Keep pre-injection, surface it inside iteration nodes in the UI only.** Rejected: the root problem is not visibility but that the agent is not the decision-maker for when state is loaded. Pre-injection keeps that structural problem intact.

**Keep pre-injection for a subset of tools (e.g., only `get_current_rover_state`).** Rejected for now: once the agent is relied upon to call tools lazily, partial pre-injection is inconsistent. Revisit only if quality evaluation shows the agent reliably fails to call state tools for rover-state queries.
