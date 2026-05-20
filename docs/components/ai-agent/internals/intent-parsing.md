# Rover Intents And Intent Test

> **UI status (2026-05-12).** The dedicated `Intent Test` mode button has been hidden as part of the AI restructure. The same parsing surface is now reached via the `/intent <prompt>` slash command in the `/ai` composer, which calls the same `POST /api/ai/sessions/{id}/intent-test` endpoint. Everything in this document about the intent model, parser behaviour, output schema, and inspection panel remains accurate — wherever the text says "Intent Test mode", read "the `/intent` slash command surface".

## Purpose

This document explains two closely related concepts in the GCS AI page:
- the rover intent model used to convert an operator request into structured fields
- the rover-intent inspection surface in `/ai` (formerly the `Intent Test` mode button, now the `/intent` slash command), which exists to inspect that parsing step without executing anything

This is an operator-safety and engineering-debugging feature.
It answers a simple but important question:

What did the system think the operator meant?

That question needs an explicit surface because later planning and execution layers depend on it.
If the system misreads the request at this stage, every later step is built on the wrong input.

## What A Rover Intent Is

A rover intent is a structured interpretation of a natural-language operator request.
Instead of keeping the request only as free text, the GCS asks an LLM to convert it into a predictable JSON object.

Current intent fields include:
- `intent_type`
- `summary`
- `target`
- `area`
- `requested_actions`
- `constraints`
- `requires_rover_motion`
- `requires_operator_approval`
- `missing_information`
- `confidence`

The current parser is designed for rover-task understanding, not open-ended chat.
It is deliberately narrower than the normal Chat mode and more constrained than Agent mode.

## Why The System Needs Structured Intent

Natural-language prompts are convenient for operators, but they are not a stable interface for planning or safety logic.
The system needs a machine-readable intermediate form so downstream components can reason about:
- whether motion is being requested
- what object or area the operator is referring to
- what information is still missing
- whether a later plan should be blocked pending clarification
- whether operator approval is mandatory before any rover motion

This intermediate representation is the contract between free-form language and later structured workflows.

In practical terms, structured intent is what allows the system to distinguish:
- “tell me what is in front of the rover”
- “inspect the solar plant on the left”
- “drive to the operations building”
- “compare this replay to the current rover state”

Those requests may all look similar at the chat layer, but they lead to different planning and safety behavior.

## Current Intent Types

The current prompt/schema expects one of these `intent_type` values:
- `navigate_to_object`
- `inspect_area`
- `search_area`
- `report_status`
- `compare_replay`
- `unknown`

The parser may still return `unknown` when the message is ambiguous, outside scope, or malformed.
That is valid behavior and should not be treated as a system failure by itself.

## What The `/intent` Slash Command Does

The `/intent <prompt>` slash command in the AI page composer is non-executing.

When typed, the GCS does not run normal chat and does not run the read-only tool-using agent loop for that message.
Instead, it sends the prompt body (everything after `/intent`) to the intent parser endpoint:
- `POST /api/ai/sessions/{session_id}/intent-test`

The backend then:
1. resolves the model to use for intent parsing
2. builds a compact current-context summary
3. invokes the structured parser prompt
4. validates and repairs the JSON once if needed
5. stores both the user prompt and assistant result in the AI session
6. renders a dedicated intent panel in the UI

If the parsed intent implies rover motion and includes a target description, the backend may also run deterministic spatial target resolution to show likely matching scene objects.
This is still analysis only.
It does not move the rover or stage commands.

## What Intent Test Mode Does Not Do

`Intent Test` does not:
- drive the rover
- publish MQTT control commands
- create an execution-capable plan
- enter the normal Agent tool loop
- approve anything
- bypass human approval rules

It is intentionally non-executing.

Even when the parser says a task requires motion, the result is only a structured interpretation and optional target-resolution aid.

## Why Intent Test Exists As A Separate Mode

The main reason is isolation.

If parsing is blended invisibly into general chat, it becomes hard to answer basic diagnostic questions:
- Did the model understand the task?
- Did it classify the task type correctly?
- Did it identify the right target?
- Is it missing critical information?
- Is the problem in parsing, spatial resolution, mission drafting, or later workflow logic?

`Intent Test` separates those concerns.

It gives operators and developers a safe place to validate the language-to-structure step before any planning layer is involved.
That makes it useful for:
- checking how the system interprets a task
- comparing provider behavior for parsing
- tuning prompts and routing
- debugging failures in mission-planning workflows
- validating safety-relevant classification such as `requires_rover_motion`

## How It Differs From Other AI Modes

### Chat

`Chat` is general conversational use of the selected provider with compact live rover/GCS context.
It is read-only, but it is not constrained to return a rover-intent schema.

Use `Chat` when you want explanation, discussion, summarization, or ordinary question-answer behavior.

### Agent

`Agent` is still read-only, but it can use deterministic tools such as rover-state, scene-summary, object-query, mission-state, and replay-analytics tools when the provider/runtime supports tool calling.

Use `Agent` when you want grounded answers that may need tool lookups.

### Intent Test

`Intent Test` is not for general conversation.
It is for parsing an operator task into structured intent and showing the result explicitly.

Use it when the key question is:
Did the system understand the requested rover task correctly?

### Planning Shell

The planning shell sits after intent parsing in the intended workflow.
It uses parsed intent plus target/context resolution to produce a mission
draft that requires draft approval. Reached via `/plan <prompt>`.

Use it when you want a supervised mission-planning flow.

In short:
- `Chat` explains
- `Agent` investigates with read-only tools
- `Intent Test` parses operator intent
- the planning shell (via `/plan`) plans a supervised mission draft

## Provider Routing For Intent Parsing

Intent parsing does not have to use the same model as general chat.

The current provider resolution order is:
1. `command_parser`
2. `planner`
3. `general_chat`

This allows the system to use a model specialized or selected for structured parsing even when the operator is otherwise chatting with another provider.

That separation matters because good conversational models and good structured-parser models are not always the same choice.

## Current Parser Prompt Contract

The parser prompt tells the model to:
- return only a JSON object
- keep `intent_type` within the allowed enum
- mark motion tasks as requiring operator approval
- avoid inventing coordinates, distances, or object identifiers
- list missing required information explicitly
- provide a confidence score

The parser currently gets one repair attempt if the first model output is invalid JSON or fails schema validation.

This is deliberately stricter than normal chat because downstream systems need predictable fields rather than prose.

## UI Output And What To Look For

The AI page renders a dedicated intent panel for `Intent Test` results.

Current fields shown to the operator include:
- intent type
- summary
- confidence
- whether motion is required
- parsed target details
- missing information
- parse errors
- candidate spatial matches when target resolution is available

When reviewing an intent result, focus on:
- whether the task type is correct
- whether the target description matches the operator’s wording
- whether the system is asking for clarification when it should
- whether `requires_rover_motion` is set correctly
- whether confidence is consistent with the ambiguity of the input

## Examples

### Example 1: Read-Only Question

Operator prompt:
`What objects are directly in front of the rover?`

Likely parse outcome:
- `intent_type`: `report_status` or `unknown`, depending on wording
- `requires_rover_motion`: `false`
- no planning should follow from this alone

This is often a better fit for `Agent` than `Intent Test`, but `Intent Test` can still show how the parser classifies it.

### Example 2: Motion Task

Operator prompt:
`Drive to the operations building and inspect the entrance.`

Expected characteristics:
- motion-related intent type
- `requires_rover_motion: true`
- `requires_operator_approval: true`
- target description preserved from the prompt

If the target can be matched in the scene map, candidate objects may be shown.

### Example 3: Ambiguous Task

Operator prompt:
`Go over there and check it out.`

Expected characteristics:
- low confidence
- incomplete or `unknown` target
- `missing_information` populated
- possible clarification need instead of a confident plan

This is a good example of why the feature exists: it lets you see ambiguity clearly instead of hiding it inside a later plan.

## Operational Use Cases

### Operator Validation

Before submitting a more formal mission request, an operator can test whether the system understood the intended target and action.

### Provider Evaluation

When comparing LLM providers, `Intent Test` gives a narrow, repeatable surface for checking structured-output quality.
That is more useful than comparing providers only on free-form chat fluency.

### Safety Review

The mode makes it obvious whether the system classifies a request as motion-related.
That is a critical boundary for later approval workflows.

### Debugging Planning-Shell Failures

If the planning shell produces a poor mission draft, `Intent Test` helps determine whether the fault began earlier in intent parsing.

## Current Limitations

The current system still has important limits:
- intent parsing is LLM-based and can misclassify ambiguous prompts
- the intent schema is intentionally narrow and does not cover every future rover task
- target resolution depends on the available live rover pose and scene-map data
- `Intent Test` validates interpretation, not physical executability
- no autonomous execution path is exposed through this feature

It should be treated as a structured interpretation aid, not as proof that a task is safe or feasible.

## Recommended Operator Guidance

Use `Intent Test` when:
- the request involves movement, inspection, search, or target selection
- you want to confirm what the system inferred
- you are troubleshooting planning-shell or parser behavior
- you are evaluating model/provider quality for structured rover-task understanding

Do not use `Intent Test` when:
- you only want a normal conversational answer
- you want live grounded investigation of the current scene; use `Agent` for that
- you expect the rover to act immediately; this mode is non-executing

## Relationship To Future Workflow

The long-term intended flow is:
1. operator provides a natural-language task
2. system parses structured intent
3. system resolves targets and context
4. system generates a draft mission
5. operator reviews and approves or rejects
6. a future controlled execution layer may stage commands under separate safety rules

`Intent Test` is the explicit inspection window for step 2.

That makes it a foundational feature even though it does not execute anything by itself.

## Source Pointers

Primary implementation files:
- `gcs_server/ai/intent_service.py`
- `gcs_server/ai/prompts.py`
- `gcs_server/ai/schemas.py`
- `gcs_server/app.py`
- `gcs_server/static/ai.html`
- `gcs_server/static/ai.js`

Related higher-level references:
- [GCS Overview](../../../technical/gcs/overview.md)
- [GCS API And Runtime](../../../technical/gcs/api-and-runtime.md)
- [Planning Shell](./workbench-mode.md)
- [AI Agent Requirements](../requirements.md)
