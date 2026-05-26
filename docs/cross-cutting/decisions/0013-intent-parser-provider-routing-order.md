# 0013. Intent-Parser Provider Routing Order: `command_parser` → `planner` → `general_chat`

Date: 2026-05-26
Status: Accepted

## Context

Intent parsing converts a free-text operator request into a structured JSON object with fields like `intent_type`, `target`, `requires_rover_motion`, and `missing_information`. The parser prompt is strict: enum-bounded, JSON-only output, with one repair attempt.

Good conversational models and good structured-parser models are not always the same choice. A model that excels at chat may produce diffuse prose under the parser prompt; a model trained or selected for structured output may be a poor fit for general dialogue. Forcing the intent parser to share the operator's currently-selected chat provider blends these two qualities into one configuration knob.

## Decision

Intent parsing resolves its provider through an ordered fallback chain that is independent of the general-chat provider:

1. `command_parser` — explicit provider configured for structured parsing
2. `planner` — provider configured for planning workflows (used as parser when no dedicated parser provider is set)
3. `general_chat` — last-resort fallback to whatever the operator is otherwise chatting with

The first non-null resolution wins.

## Consequences

- Intent parsing can be pinned to a small/specialized model even when the operator chats with a larger or different provider.
- The planning shell, which depends on parsed intent, gets the same routing behavior without separate configuration.
- Misconfiguration is non-fatal: `general_chat` is always a valid last resort, so the parser never fails purely on provider absence.
- Changing the parser provider does not change conversational behavior, and vice versa — the two concerns evolve independently.

## Alternatives Considered

- **Always use the active chat provider.** Rejected: forces operators to pick a chat provider that is also competent at strict structured output.
- **Hard-require a dedicated `command_parser` setting.** Rejected: too brittle for development and demo configurations; the fallback chain keeps the surface usable without configuration.

## Follow-Ups

- Companion design lives in [`docs/components/ai-agent/design.md`](../../components/ai-agent/design.md) § "Provider Routing For Intent Parsing".
