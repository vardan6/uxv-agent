# 0010. "Internals" Is The Name Of The Third Documentation Tier

Date: 2026-05-20
Status: Superseded 2026-05-26 — the `internals/` tier was eliminated and its content folded into each component's `design.md`. See § Supersession at the bottom of this ADR.

## Context

The documentation restructure (see `restructure-plan.md`) introduced a three-tier model: a locked stakeholder layer, an agreed external-behavior layer, and a living implementation layer. The first two were quickly named `requirements.md` and `design.md`. The third tier was initially proposed as `reference.md` / `reference/`.

During the grilling session, "reference" surfaced two problems:

1. It collides with the everyday meaning of "reference material" (something you cite, not something you rewrite). The third tier is precisely the layer an AI agent rewrites during normal work — the opposite of "reference."
2. It does not communicate the "how the code currently does it" intent. A reader scanning `requirements / design / reference` reads it as three stable artifacts of equal weight.

The user proposed "internals" as the alternative.

## Decision

The third documentation tier is named **internals**. The folder is `internals/`, with one file per concept (`design.md`, `design.md`, etc.). The name appears in folder paths only — never inside file content, since tier is conveyed by location, not by labels.

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

## Supersession (2026-05-26)

After the Pass-1 + Pass-2 trim, every surviving `internals/*.md` file was ≥80% design-shaped (contracts, invariants, state machines, decisions), with implementation snapshots and dated narrative stripped out. The remaining distinction between `design.md` and `internals/<topic>.md` had collapsed: both tiers now held design-shaped content, just at different topic-granularity.

The third tier was folded into the second. Each component's `internals/*.md` files were concatenated into the corresponding `design.md`, each preserving its original `# Title` heading as a top-level section. The `internals/` directories were deleted. STYLE.md was rewritten to describe a two-tier model. Component READMEs and the components index were updated.

A follow-on pass the same day split the merged `design.md` into a thin top-level `design.md` (overview + cross-topic contracts + index) plus per-topic files under a `design/` directory (`design/<topic>.md`). This is topic-level organization *within* the design tier — every file in `design/` carries the same stability rules as `design.md`. It is **not** a re-introduction of the `internals/` tier (which had relaxed stability rules); it is purely navigation/readability for agent and human readers.

Pre-drop state is preserved at the git tag `pre-drop-internals-docs-2026-05-26`.

Rationale carried forward from this ADR: "internals" still names a real distinction (the layer an agent may freely rewrite from code), but at this point that label applies to the *bottom half* of each component's `design.md` rather than to a separate folder. The folder-path-conveys-tier convention is preserved: top of `design.md` is contract; the merged-from-internals section at the bottom is implementation-living.

Future re-introduction of a third tier would need a new ADR and a strong reason — the trim pass demonstrated that the previous split was producing more navigation overhead than navigation aid.
