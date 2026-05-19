# 0010. "Internals" Is The Name Of The Third Documentation Tier

Date: 2026-05-20
Status: Accepted

## Context

The documentation restructure (see `restructure-plan.md`) introduced a three-tier model: a locked stakeholder layer, an agreed external-behavior layer, and a living implementation layer. The first two were quickly named `requirements.md` and `design.md`. The third tier was initially proposed as `reference.md` / `reference/`.

During the grilling session, "reference" surfaced two problems:

1. It collides with the everyday meaning of "reference material" (something you cite, not something you rewrite). The third tier is precisely the layer an AI agent rewrites during normal work — the opposite of "reference."
2. It does not communicate the "how the code currently does it" intent. A reader scanning `requirements / design / reference` reads it as three stable artifacts of equal weight.

The user proposed "internals" as the alternative.

## Decision

The third documentation tier is named **internals**. The folder is `internals/`, with one file per concept (`internals/graph-spec.md`, `internals/context-layer.md`, etc.). The name appears in folder paths only — never inside file content, since tier is conveyed by location, not by labels.

## Consequences

- A reader seeing `internals/` immediately understands the content is implementation-bound and regenerable from code.
- An AI agent can be told "you may freely rewrite anything under `internals/`; do not edit `requirements.md` or `design.md` without approval" — and that rule maps cleanly to folder paths.
- Cross-component consistency: every fully-documented component has the same triplet (`requirements.md`, `design.md`, `internals/`).
- Future tier-name proposals (e.g., "implementation", "code-notes") are explicitly rejected by this decision to keep the vocabulary stable.

## Alternatives Considered

- **`reference.md` / `reference/`.** Rejected for the reasons above.
- **`implementation.md` / `implementation/`.** Considered. Accurate, but verbose and easy to misread as "the implementation itself" rather than docs about it. "Internals" is shorter and reads as "notes about the inside" without that ambiguity.
- **`notes/` or `code-notes/`.** Rejected: too informal, signals "scratchpad," undersells the role this tier plays in agent navigation.

## Follow-Ups

- STYLE.md and every component README use "internals" consistently. Any drift gets fixed under the rename-everywhere rule.
