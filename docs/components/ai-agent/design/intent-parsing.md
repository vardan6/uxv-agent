# Rover Intent Parsing

## Purpose

This document describes the shared rover-intent parser used by the GCS AI stack
to convert an operator request into structured fields that downstream planning
and safety logic can reason about.

Intent parsing is an internal capability. There is no dedicated `/intent`
operator-facing mode.

## What A Rover Intent Is

A rover intent is a structured interpretation of a natural-language operator
request. Instead of keeping the request only as free text, the GCS asks an LLM
to convert it into a predictable JSON object.

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

The parser is designed for rover-task understanding, not open-ended chat.

## Why The System Needs Structured Intent

Natural-language prompts are convenient for operators, but they are not a
stable interface for planning or safety logic. The system needs a
machine-readable intermediate form so downstream components can reason about:

- whether motion is being requested
- what object or area the operator is referring to
- what information is still missing
- whether a later plan should be blocked pending clarification
- whether operator approval is mandatory before any rover motion

This intermediate representation is the contract between free-form language and
later structured workflows.

## Current Intent Types

The current prompt/schema expects one of these `intent_type` values:

- `navigate_to_object`
- `inspect_area`
- `search_area`
- `report_status`
- `compare_replay`
- `unknown`

Returning `unknown` for an ambiguous or out-of-scope request is valid behavior.

## Current Parser Contract

The parser prompt tells the model to:

- return only a JSON object
- keep `intent_type` within the allowed enum
- mark motion tasks as requiring operator approval
- avoid inventing coordinates, distances, or object identifiers
- list missing required information explicitly
- provide a confidence score

The parser gets one repair attempt if the first model output is invalid JSON or
fails schema validation.

## Current Integration Points

Intent parsing is still used by shared planning and mission-authoring internals:

- `parse_rover_intent` in `ToolRegistry`
- direct Agent mission-authoring
- target and context resolution that depends on parsed operator intent

It is no longer a required standalone operator-facing mode.

## Relationship To Other AI Paths

- `Chat` is general conversational use of the selected provider.
- `Agent` is the tool-using read-only investigation path.
- direct Agent mission-authoring reaches intent parsing through planner tools
  inside the shared agent runtime.

In short:

- `Chat` explains
- `Agent` investigates with tools
- shared intent parsing structures rover-task requests for planning flows

## Relationship To Future Workflow

The intended workflow remains:

1. operator provides a natural-language task
2. system parses structured intent
3. system resolves targets and context
4. system generates a draft mission
5. operator reviews and approves or rejects
6. a future controlled execution layer stages commands under separate safety
   rules

Intent parsing remains the step-2 contract in that flow even after the
dedicated inspection surface is removed.
