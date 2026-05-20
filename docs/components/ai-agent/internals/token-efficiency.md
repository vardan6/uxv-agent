# AI Agent Token Efficiency Plan

**Status:** Phase 1 shipped + Phase 2 #6 shipped — measured 2026-05-16 against a real session; results modest for OpenAI providers (Anthropic savings invisible without cache_read telemetry). Smalltalk-bypass bug identified. Phase 3 (#2, #3) still the largest remaining win.
**Owner:** TBD
**Created:** 2026-05-16
**Last updated:** 2026-05-16

## Motivation

Observed token usage on real chat sessions shows simple replies costing **10K–18K input tokens per turn**, even for trivial messages like "hello". A representative session (`hello` → `/capabilities brief` → 4 mission-creation turns → `hello`) cost ~63K input tokens total across 7 model calls. The biggest contributors are static, repeatable content re-sent verbatim every turn with no prompt caching.

This document captures the audit, the optimization plan, and a roadmap table to track progress.

---

## Where the tokens go

Baseline cost for a typical reply (~10K input tokens) decomposes roughly as:

| Component | Tokens | Share | Source |
|---|---|---|---|
| Conversation history (16K char budget, re-sent verbatim) | ~4,000 | 38% | `gcs_server/ai/chat_service.py:33,239` |
| Live context snapshot (rover + settings + llm + mission + scene JSON) | ~2,500 | 24% | `gcs_server/ai/context_service.py:101` |
| Eager detail pre-fetches in chat mode (keyword-triggered) | ~2,000 | 19% | `gcs_server/ai/context_service.py:64-99` |
| Tool catalog descriptions (17 tools, prose-style) | ~870 | 8% | `gcs_server/ai/tool_registry.py` |
| `AGENT_SYSTEM_PROMPT` (13 instruction paragraphs) | ~480 | 5% | `gcs_server/ai/chat_service.py:18-30` |
| Tool result re-transmission across agent iterations | +500–1000 / iter | — | `gcs_server/ai/agent_loop.py:213` |

**Critical finding:** no provider-side prompt caching is configured anywhere. `grep cache_control` in `gcs_server/ai/` returns zero hits. Every turn re-bills the entire static prefix.

### Supporting observations

- 17 tools in `tool_registry.py` (79.6 KB file); average description ~204 chars, lots of "Use this when the operator…" routing hints that duplicate function names.
- `AGENT_SYSTEM_PROMPT` is 1,935 chars sent on every agent-mode turn.
- `eager_detail_mode=True` in chat mode (`context_service.py:64`) scans the user message for keywords and pre-injects `objects_in_front`, `objects_near_rover`, `replay_sessions`, `ai_chat_history` blobs — even though equivalent tools exist.
- `_context_prompt()` (`context_service.py:101`) rebuilds the full rover+settings+scene JSON every request even when nothing changed.
- Conversation log shows `get_scene_summary` invoked 3× in 6 turns with no in-session caching, and `plan_route_around_group("plant_a")` retried 3× with the same failing args.
- Conversation history (`_fit_messages_to_budget`, `chat_service.py:558-581`) re-sends prior tool results verbatim; no summarization or reference-based compression.

---

## Optimization plan — ordered by ROI

### Tier 1 — Big wins, low accuracy risk

**1. Enable provider prompt caching (Anthropic `cache_control` / OpenAI cached input)**
- Wrap `AGENT_SYSTEM_PROMPT` + tool-catalog guidance + stable base-context blocks with `cache_control: {"type": "ephemeral"}` at the model invocation site in `chat_service._prompt_for_mode()` and `agent_loop.py`.
- **Impact:** ~60–80% input cost reduction on cache hits.
- **Risk to accuracy:** zero — model sees identical content, just billed cheaper.
- **Caveat:** 5-minute Anthropic cache TTL; back-to-back turns benefit most.

**2. Stop re-sending full context snapshot every turn — context delta mode**
- Send the full snapshot only on session start (or when a change-marker fires), then per-turn send just deltas (e.g., updated pose, battery).
- **Impact:** ~2K tokens/turn saved once warm.
- **Risk:** mild — re-emit full snapshot every N turns or on telemetry-freshness flip to prevent drift.

**3. Disable eager-detail pre-fetching; let the agent use its tools**
- Set `eager_detail_mode=False` in chat mode too, OR truncate injected blocks (top 3 objects, not full lists).
- **Impact:** ~2K tokens/turn in chat mode.
- **Risk:** medium-low. Verify chat mode has tool-call access first; if not, keep a slim eager fetch.

### Tier 2 — Medium wins, needs care

**4. Compress tool descriptions in `tool_registry.py`**
- Trim each description to ≤80 chars terse "what it does"; move routing hints into one compact decision tree in the system prompt.
- **Impact:** ~500 tokens/turn.
- **Risk:** medium. Tool selection quality may degrade. Gate behind feature flag, eval before rollout.

**5. Compact conversation history — drop tool-activity JSON from rolling context**
- Replace prior tool results with one-line summaries when re-sending; keep only the most recent turn's tool results verbatim.
- **Impact:** ~1.5–2K tokens/turn on tool-heavy conversations.
- **Risk:** medium. Model loses look-back on prior tool result details.

**6. Cache tool results within a session**
- In-memory cache keyed by `(session_id, tool_name, args_hash)`; invalidate on scene/config change events.
- **Impact:** variable — eliminates redundant tool execution and shrinks iteration message lists.
- **Risk:** low if invalidation tracks real events.

### Tier 3 — Smaller wins, cleanups

**7. Tighten `AGENT_SYSTEM_PROMPT`** — 1,935 chars → target ~600. Saves ~350 tokens/turn.

**8. Cap retry-on-same-failure in agent loop** — detect identical `(tool, args)` repeats after failure; short-circuit with the prior error.

**9. Minify JSON context blobs** — ensure `separators=(",",":")` everywhere user-visible JSON isn't required.

---

## Phasing & expected savings

| Phase | Changes | Expected baseline drop | Effort |
|---|---|---|---|
| **Phase 1** (1–2 days) | #1 prompt caching, #7 prompt trim, #8 retry guard | 10K → ~3–4K on cache hits | Small |
| **Phase 2** (2–3 days) | #3 disable eager pre-fetch, #4 tool description compaction, #6 result caching | additional ~30% | Medium, needs eval |
| **Phase 3** (3–5 days) | #2 context delta mode, #5 history compaction | sub-2K cold, sub-1K warm | Larger, needs invalidation logic |

**Realistic target:** **10K → 1.5–3K tokens/turn** sustained, with cache hits dropping warm-turn cost ~80% further.

---

## Accuracy protection plan

Before merging Tier 2 / Tier 3 changes:

1. **Regression set:** ~20 real conversations from `session_store` covering spatial queries, route planning around groups, replay analytics, drive-to missions, ambiguous prompts.
2. **Eval harness:** run each against current vs. optimized code; score tool-call correctness + final-answer correctness.
3. **Gate rollout** on no-regression per phase.
4. **Feature flags** for verbose tool descriptions and full eager-detail mode so we can toggle back without a redeploy.

---

## Roadmap status

Update the **Status** column as work progresses. Suggested values: `Not started` · `In progress` · `Blocked` · `In review` · `Shipped` · `Reverted`.

### Phase 1 — Cache & quick trims

| # | Change | Files | Owner | Status | Measured savings | Notes |
|---|---|---|---|---|---|---|
| 1 | Provider prompt caching (`cache_control`) | `agent_loop.py` (`_build_system_message`, `_is_anthropic_model`, `_prompt_cache_enabled`); `prepare_tool_runtime` | claude | Shipped 2026-05-16 | Pending (need cache_read telemetry) | Anthropic only (`cache_control: ephemeral` on first SystemMessage); OpenAI auto-caches identical prefixes server-side. Kill switch: `AI_PROMPT_CACHE_DISABLED=1`. |
| 7 | Tighten `AGENT_SYSTEM_PROMPT` (1935 → 1011 chars) | `chat_service.py:18-27` | claude | Shipped 2026-05-16 | ~230 tokens/turn (48% prompt reduction) | All semantic rules preserved (read-only, path_length_m mapping, telemetry fallback, fail-plainly, no-fabrication). |
| 8 | Retry-on-same-failure guard in agent loop | `agent_loop.py:147-155,200-212` | (pre-existing) | Shipped (pre-existing) | Already saving on retries | `AI_AGENT_MAX_REPEATED_TOOL_FAILURES=2` short-circuits identical `(tool_name, args)` failures within an agent loop. Cross-turn repeats are out of scope for Phase 1 — addressed by #6 (session tool cache). |

### Phase 2 — Eager-mode & tool catalog

| # | Change | Files | Owner | Status | Measured savings | Notes |
|---|---|---|---|---|---|---|
| 3 | Disable / truncate eager detail pre-fetch | `context_service.py:64-99` | — | Not started | — | Confirm chat-mode tool access; flag-gate |
| 4 | Compress tool descriptions to ≤80 chars | `tool_registry.py` | — | **Deferred** (2026-05-16) | — | Skipped per user direction: recent fixes tuned the descriptions and trimming risks regression. Revisit only with an eval harness in place. |
| 6 | In-session tool result cache | `ai/tool_result_cache.py` (new), `ai/agent_loop.py`, `ai/chat_service.py` | claude | Shipped 2026-05-16 | Compute/latency win; token-neutral within a single agent loop. Cross-turn benefit: avoids re-executing `get_scene_summary` etc. when conversation revisits stable data. | Module-level TTL cache keyed by `(session_id, tool_name, args_hash)`. 17 allowlisted read-only tools (excludes pose- or telemetry-dependent ones). Only `ok: true` results cached. Kill switch: `AI_TOOL_RESULT_CACHE_DISABLED=1`. |

### Phase 3 — Context delta & history compaction

| # | Change | Files | Owner | Status | Measured savings | Notes |
|---|---|---|---|---|---|---|
| 2 | Context delta mode (full snapshot on session start, deltas thereafter) | `context_service.py`, `chat_service.py` | — | Not started | — | Re-emit full snapshot every N turns; freshness-driven invalidation |
| 5 | Summarize older tool results in rolling history | `chat_service.py:558-581`, `agent_loop.py` | — | **Deferred** (2026-05-16) | — | Skipped per user direction: medium accuracy risk (model loses look-back on prior tool result detail). Revisit with eval harness. |
| 9 | Minify JSON context blobs | various | — | Not started | — | Low-risk cleanup |

### Cross-cutting

| Item | Status | Notes |
|---|---|---|
| Token-usage telemetry per turn (input / output / cache_read / cache_write) | Not started | Required to verify savings end-to-end |
| Regression eval set (~20 conversations) | Not started | Pull from `session_store`; cover spatial / route / replay / mission |
| Feature flags: `ai.verbose_tool_descriptions`, `ai.eager_detail_mode`, `ai.context_delta_mode`, `ai.prompt_cache` | Not started | Allow per-flag rollback without redeploy |

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-05-16 | Plan drafted, awaiting approval for Phase 1 | Highest ROI (prompt caching) is zero-accuracy-risk; safe starting point |
| 2026-05-16 | Phase 1 shipped (#1, #7); #8 confirmed pre-existing | #7 trimmed prompt to 1011 chars (-48%). #1 adds Anthropic `cache_control` on first system message; gated by `AI_PROMPT_CACHE_DISABLED` env var. Detection by class-name sniff (no new dep on `langchain_anthropic`). OpenAI path unchanged — server-side caching is automatic given stable prefix order. |
| 2026-05-16 | Phase 2 partial: #6 shipped; #4 and #5 explicitly deferred | User directive: tool descriptions are tuned by recent fixes, do not regress (#4 skipped); history compaction has medium accuracy risk (#5 skipped). #6 is honest about scope — it saves tool execution latency and cross-turn redundant work, not input tokens directly. Real token-savings tools remain Phase 1 (caching) and Phase 3 (#2 context delta, #3 eager pre-fetch removal). |
| 2026-05-16 | Post-Phase-1 measurement: real session showed ~50% drop on conversational turns, ~5–15% on tool turns. Net less than hoped. | See "Post-Phase-1 measurement" section. Three reasons identified: (a) session used OpenAI provider, so Anthropic `cache_control` markers no-op; OpenAI auto-caches but discount is invisible in the UI counter; (b) #6 saves compute not tokens (already documented); (c) the biggest token sinks (live context snapshot, eager-detail prefetch) are Phase 3 work and untouched. Also found a one-line bug: smalltalk bypass at `chat_service.py:606-618` only matches a fixed set, so "hello again" and "how are you ?" (trailing space) fall through to agent mode and pay full price. |

---

## Post-Phase-1 measurement (2026-05-16)

Real session captured after Phase 1 + Phase 2 #6 shipped. Provider: gpt-5.4-nano (OpenAI-compatible). Compared to the pre-optimization session referenced in [Motivation](#motivation).

### Side-by-side

| Turn type | Before | After | Delta |
|---|---|---|---|
| "hello" (cold start, Ollama, chat mode) | 310 | 311 | — |
| 2nd casual ("hello again", agent mode) | ~18K | 8.6K | **-52%** |
| "how are you?" (agent mode) | n/a | 8.7K | (smalltalk bypass missed) |
| Tool turn ("what solar plants…") | 18K | 17K | -6% |
| Mission plan (route around group) | 11K | 9.3K | -15% |
| Mission follow-ups | 10–11K | 9.5–11K | -5–10% |

### Why the visible savings are smaller than designed

1. **OpenAI provider hides the cache discount.** The session uses gpt-5.4-nano. The `cache_control: ephemeral` marker we added in Phase 1 #1 only fires for Anthropic models. OpenAI does cache identical prefixes automatically and bills cached tokens at ~50%, but the UI's "input tokens" counter still shows the gross count. Estimated real savings 30–40% on cached input billing are invisible until we surface `prompt_tokens_details.cached_tokens` from the response metadata.
2. **Phase 2 #6 was always compute-only.** The cache prevents redundant Dijkstra/scene compute (same `route_hash 764db72c23a0` appeared across four turns), but the model still calls the tool and ingests the result each turn — tokens unchanged. Documented in the #6 row; restated here so we don't expect token wins from it.
3. **The two largest token sinks are still in Phase 3.** Per the original audit:
   - Live context snapshot (~2,500 tokens/turn) — Phase 3 #2 not started.
   - Eager-detail prefetch (~2,000 tokens/turn in chat mode) — Phase 3 #3 not started.

### Bug identified during measurement

`_is_trivial_agent_smalltalk` (`gcs_server/ai/chat_service.py:600-619`) bypasses agent mode for trivial greetings and routes the turn through the cheap `SYSTEM_PROMPT` path. The current match set is a fixed exact-equality lookup:

```python
{"hi","hello","hey","yo","sup","hiya",
 "good morning","good afternoon","good evening",
 "how are you","how are you?"}
```

Misses observed in the real session:
- `"hello again"` → not in set → falls through → 8.6K input
- `"how are you ?"` (trailing space before `?`) → no exact match → falls through → 8.7K input

Fix candidates:
- Normalize: strip punctuation/whitespace before comparison.
- Or: add a short startswith-prefix check (`"hi"`, `"hello"`, `"hey"`, `"thanks"`, `"thank you"`, `"ok"`, `"okay"`, `"yes"`, `"no"`) gated by a small length cap (e.g. ≤40 chars).

Either reduces "hello again"-style turns from 8.6K → ~300 tokens. One-line patch, very low risk (only affects messages that already match the trivial-smalltalk shape).

### Recommended next moves

Ordered by ROI per effort.

| # | Change | Effort | Expected savings/turn | Risk |
|---|---|---|---|---|
| A | Widen smalltalk bypass (normalize + prefix matching) | Trivial | -8K on chitchat turns | Very low |
| B | Surface OpenAI `prompt_tokens_details.cached_tokens` in usage metadata + assistant message meta | Small | 0 directly, but reveals Phase 1 #1 effectiveness for OpenAI | Zero |
| C | Phase 3 #3 — disable / aggressively truncate eager-detail prefetch in chat mode | Small–medium | -1.5–2K | Low (model can call tools instead) |
| D | Phase 3 #2 — context delta mode (full snapshot on session start, deltas thereafter) | Medium | -1.5–2K | Medium (needs change-detection / invalidation) |

Projected post-A+B+C+D:
- Casual chitchat turn: 8.6K → **~500 tokens**
- Tool-using turn: 9–17K → **~3–5K**

### Cross-cutting follow-ups added

| Item | Status | Notes |
|---|---|---|
| Smalltalk bypass coverage gaps | Open | See bug above; add to Phase 1 cleanup or treat as a one-off patch |
| OpenAI cached-token telemetry | Open | Required to prove Phase 1 #1 is effective for the OpenAI path; without it the cache_control work is unmeasurable for non-Anthropic users |

---

## Accuracy follow-ups (not token-related, but observed during measurement)

Smaller-model variants (e.g. gpt-5.4-nano) struggled to recover from `plan_route_around_group` failures observed in the pre-fix transcript: the model guessed `group_id="plant_a"`, the road graph wasn't loaded yet (`known_groups: []`), and the model gave up rather than fall back to `plan_route_between`. The full-size model handled this correctly. Two small changes shipped 2026-05-17 to help weaker routers:

### A1 — Structured error payload for `plan_route_around_group` (shipped 2026-05-17)

`gcs_server/ai/tool_registry.py:_plan_route_around_group`

Replaced flat error string with a structured payload that exposes a recovery path:

```json
{
  "ok": false,
  "error": "unknown group 'plant_a'",
  "known_groups": [],
  "scene_may_be_loading": true,
  "fallback_tool": "plan_route_between",
  "hint": "No route groups are registered for this scene yet — the road graph may still be building. Either retry once, or use plan_route_between with explicit start/goal targets resolved via resolve_spatial_target."
}
```

Only the failure-case return value changed — descriptions untouched, success path unchanged. Risk: very low.

### A2 — System prompt nudge (shipped 2026-05-17)

`gcs_server/ai/chat_service.py:AGENT_SYSTEM_PROMPT`

Added one sentence:

> If a failed tool result includes a `hint` or `fallback_tool` field, follow it (try the suggested tool/strategy) before asking the operator for clarification.

Costs ~25 tokens/turn. Unlocks the recovery path A1 introduces. Risk: low (additive, consistent with read-only behavior).

### Not done (proposed but not needed yet)

- **A3 — `route_groups_hint` in `get_scene_summary`** when `route_groups == []`. Deferred: A1's payload already catches the empty-group case at the failure site, and `route_groups` is already returned by scene_summary. Revisit only if smaller models still get stuck after A1+A2.
- Description rewrites of `plan_route_around_group` / `get_scene_summary` — explicitly not done per existing direction (no regression on tuned descriptions).
- New `list_route_groups` tool — redundant with `get_scene_summary.route_groups`.
- Fuzzy matching of `group_id` — too unpredictable; skipped.

### Decision log entry

| Date | Decision | Rationale |
|---|---|---|
| 2026-05-17 | A1 + A2 shipped together | Small-model variants (gpt-5.4-nano) couldn't recover from `unknown group` failures observed in the measurement transcript. A1 changes only the failure-case payload (no description churn, no behavior change on success). A2 is one additive sentence in the system prompt, consistent with existing read-only guidance. Combined risk: very low. Tests: same 30 pass / 2 pre-existing fail / 16 pre-existing error as baseline. |
