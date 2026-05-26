# 0014. Replay Session Reference Resolution Happens Server-Side, Not In The Model

Date: 2026-05-26
Status: Accepted

## Context

Operator queries about replay sessions use relative references: "the last session", "yesterday's run", "the one before last", "third from last", "today's sessions". Resolving these to concrete session IDs requires decisions about:

- which timestamp field defines ordering (`started_at` vs `ended_at`)
- what "last" means (most recently started? most recently completed?)
- which timezone defines a calendar day
- how to disambiguate when multiple sessions match

Letting the LLM resolve these references implicitly is tempting — it reads natural — but it makes the resolution rule non-deterministic, untestable, and dependent on whichever model is currently in use.

## Decision

Session reference resolution happens in backend code before any model reasoning. The model never sees raw timestamps or session-selection logic; it receives already-resolved session IDs and compact structured summaries.

Canonical resolution rules:

- Default sort: `started_at DESC`.
- `last session` = most recently started session.
- `the one before last` / `third from last` = second / third item in `started_at DESC`.
- `first session` = oldest item in `started_at ASC`.
- Date selectors (`today`, `yesterday`) compare against `started_at` in an explicit local timezone.

Selection priority when multiple sources could supply the session:

1. explicit session ID in the user request
2. replay sessions explicitly attached or selected by the UI
3. the active replay session for live-context questions
4. clarification when multiple sessions are plausible

## Consequences

- Replay analytics is testable without a model in the loop: a deterministic backend function maps `"last session"` to a session ID.
- The same resolution rule serves the replay UI, AI tools, and any future workflow orchestration — there is one canonical answer to "what does `last` mean".
- If product language later needs different meaning (e.g. "last completed session"), it is expressed via explicit phrasing rather than by silently changing the default ordinal rule.
- Models can still phrase clarification questions, but they cannot invent resolution semantics.

## Alternatives Considered

- **Let the model resolve references via tool calls returning raw timestamps.** Rejected: non-deterministic across model versions, harder to test, harder to audit.
- **Encode resolution rules in the parser prompt.** Rejected: pushes a hard requirement into a soft surface and breaks if the parser is swapped.

## Follow-Ups

- Companion design lives in [`docs/components/ai-agent/internals/replay-access.md`](../../components/ai-agent/internals/replay-access.md) § "Session Reference Resolution".
