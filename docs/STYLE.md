# Documentation Style Guide

How Remote Rover documentation is organized, named, written, and retired. This file is the source of truth for documentation conventions. When the conventions here disagree with an existing doc, the doc is wrong — fix it.

This guide is **agent-neutral**: every convention here works for any AI agent or human reading the repo. No Claude-specific, Codex-specific, or other tool-specific files belong in `docs/`.

## Stability Tiers

Every documented component has up to three tiers of documentation. The tier determines who can change it and when.

| Tier | Filename pattern | Changes when |
|---|---|---|
| **Requirements** | `<component>/requirements.md` | Only when the user explicitly asks. Locked otherwise. |
| **Design** | `<component>/design.md` | Only after discussion and approval. Captures agreed behavior and contracts. |
| **Internals** | `<component>/internals/<topic>.md` | Freely, to track what the code currently does. Regenerable from code. |

A component is "fully documented" when all three tiers exist. Internals is the layer an AI agent can rewrite during normal work; the other two are not.

Tier is **not** stated inside the file. The folder path conveys it. Don't restate the obvious.

## Folder Layout

```
docs/
  README.md                 # short index of this folder
  STYLE.md                  # this file
  glossary.md               # shared vocabulary, on-demand reference

  components/
    README.md               # one-screen table: per-component tier completeness
    ai-agent/
      README.md             # short index of this component's docs
      requirements.md
      design.md
      internals/
        README.md
        <topic>.md
        ...
    gcs/
      README.md
      requirements.md
      design.md
      internals/...
    simulator/
      README.md
      requirements.md
      design.md
      internals/...

  cross-cutting/
    README.md
    architecture.md         # system-wide components, data flows, MQTT contract
    decisions/              # ADRs, numbered
      0001-<slug>.md
      ...
    operations/             # run-and-config and operational guides
    research/               # third-party background material (e.g., USD, flight controllers)

  archive/
    README.md
    <area>/                 # mirrors live tree: ai-agent/, gcs/, simulator/, cross-cutting/
      YYYY-MM-DD-<slug>.md
```

### What lives where

- **A component folder** (`components/<name>/`) exists only for components with stakeholder-facing requirements. Internal helpers (e.g., `tts`, `config`) collapse into a single README and fold their requirements into a parent component's docs.
- **Cross-cutting** is for content that doesn't belong to one component: system architecture, ADRs, operations, third-party research.
- **Archive** is for traceability. Anything in archive is not the source of truth.
- **Repo-root workflow files** such as `activeContext.md` and `roadmap.md` are outside `docs/`. They track session/workflow state, not canonical product design.

## Naming

- **Lowercase, dash-separated.** `operator-experience.md`, not `OperatorExperience.md` or `operator_experience.md`.
- **Stable concept names, not session names.** `mission-execution.md`, not `mission-execution-plan-2026-05-12.md`.
- **No dates in active filenames.** Git history provides dates. Date-stamped filenames belong only in `archive/` (format: `YYYY-MM-DD-<slug>.md`).
- **Singular nouns by default.** `decision`, `provider`, `mode`.
- **Tier filenames are fixed.** Always `requirements.md`, `design.md`, `internals/<topic>.md`. Never invent a fourth name.

## File Header

Every doc starts with a title and a one-paragraph summary, then the body. No frontmatter, no tier labels, no metadata block.

```markdown
# Spatial Tools

The spatial query service exposes deterministic object-position queries to AI
tools. Backed by the terrain scene manifest. Does not cover live rover state
— see [context-layer.md](./context-layer.md).

## <first section>
...
```

The summary paragraph answers: what does this doc cover, and what does it *not* cover? Aim for ≤ 4 sentences. This is the cue an agent (or you) uses to decide in 5 seconds whether to keep reading.

Folder `README.md` files use the same shape: title + one paragraph + a table or list of children with one-line hooks. No tier label (READMEs are pure navigation).

## Size Targets

Soft targets. Split a file by topic when it grows past the cap.

| Tier | Target lines | Hard cap |
|---|---|---|
| Requirements | ≤ 400 | 600 |
| Design | 400-700 | 1000 |
| Internals (single topic) | 300-500 | 800 |
| Folder README | ≤ 80 | 150 |

When an internals file would exceed its cap, split by topic, not by length. Each new file gets a clear single-concept name.

## Cross-Linking

- **Relative paths inside `docs/`.** `[design](../design.md)`, not absolute.
- **Repo paths for code.** `gcs_server/ai/context_service.py`, not a URL.
- **Always link with `.md` extension.** Renders on GitHub; agent-friendly.
- **Glossary on first use.** When introducing a project term in a doc, link it to `glossary.md` on first use.
- **Two-link rule between tiers.** `requirements.md` links to `design.md`. `design.md` links back to `requirements.md` and out to relevant `internals/*.md` files. `internals/*.md` links back to `design.md`. No tier reads as an island.

## Single Source Of Truth

If two docs say the same thing, one is wrong. Link instead of restate.

- Requirements states *what* and *why*. Design links to requirements; does not restate them.
- Design states *how it behaves* externally and *what it commits to*. Internals link to design; do not restate the contract.
- Internals state *how the code currently does it*.

When a fact in a doc could be derived from the folder path (tier, component), don't write the fact in the doc.

## Rename And Move

When a file is renamed, moved, or merged: **update every reference to its old path in the same change**. No broken links. No stale paths left in sibling docs. This applies to:

- Other docs in `docs/`
- `README.md` files at the repo root and in component subdirectories
- Any code comment or docstring that links to docs
- `docs/STYLE.md` itself if it mentions the file

A rename is not done until references are updated.

## Diagrams

- **Mermaid in fenced code blocks.** Renders on GitHub, agent-readable as text, version-controllable as plain text.
- **No binary images** for things Mermaid can express (sequence diagrams, flow charts, state machines, component diagrams).
- **Binary images allowed** only for screenshots, UI mockups, or content that genuinely cannot be expressed in text. Store under `<component>/mockups/` or `<component>/assets/`.

## Archive

A doc moves to `archive/` when any of the following are true:

- **Superseded.** Its content has been merged into a canonical doc.
- **Handoff doc whose work is done.** Implementation handoffs, "next-session plans" — archive once the work landed.
- **Review output.** Per-date code-review session output — archive once findings are either fixed or captured in the relevant component doc.
- **Dated filename.** A `YYYY-MM-DD-...` filename is inherently transient.
- **Abandoned.** A plan for an approach that was not taken.

**Extract before archive.** Before moving anything to archive, port its non-obvious decisions, design rationale, diagrams, and implementation knowledge into the appropriate canonical doc (component `design.md`, an `internals/*.md`, or a new ADR). Archive is for traceability, not for hiding still-useful content. "Implemented already" is *not* sufficient cause to archive without extraction — the *why* often outlives the *what*.

Archive folder structure mirrors the live tree, with dated filenames:

```
archive/ai-agent/2026-05-10-llm-provider-implementation-handoff.md
archive/gcs/2026-05-11-claude-code-review.md
archive/simulator/2026-04-mqtt-plan.md
```

## Decision Records (ADRs)

ADRs live in `cross-cutting/decisions/<number>-<slug>.md`. Numbering is monotonic; never reuse a number.

```markdown
# <number>. <Title>

Date: <yyyy-mm-dd>
Status: Accepted | Superseded by <link> | Deprecated

## Context

What problem prompted this decision? What constraints applied?

## Decision

What did we decide?

## Consequences

What does this enable, prevent, or require? What follow-ups exist?

## Alternatives Considered

What else was on the table and why was it rejected?
```

When superseding an ADR, change its status to "Superseded by <link>" and add a new ADR. Do not delete or edit the original decision.

## Plans Are Living, Not Permanent

A "plan" doc captures intended future work. When the work is done:

- if the plan content is now description of the implementation, fold it into the matching `design.md` and `internals/*.md`
- if the plan content is no longer relevant, extract any still-useful decisions to an ADR and archive
- never leave executed plans on the active surface

## Repo-Wide Status

Do not maintain a second active status hub under `docs/`.

- Put current implementation reality in the relevant component `design.md` or `internals/*.md` file.
- Put current product intent in the relevant component `requirements.md`.
- Put cross-component rationale in `cross-cutting/vision.md`, `cross-cutting/architecture.md`, or an ADR.
- When retiring a high-level summary or plan doc, move the old file to `archive/cross-cutting/` and leave at most a short compatibility stub at the old path if historical links need to keep resolving.

Everything else is discovery-on-demand. Do not add new "mandatory load" docs. Predictable paths and folder READMEs do the job.

## Tone And Voice

- **Direct, third-person, present tense.** "The GCS publishes presence" not "The GCS will publish presence" or "We publish presence."
- **No filler praise.** Skip "robust", "comprehensive", "powerful". State what the system does.
- **Distinguish what is from what is planned.** Use clear markers: "Implemented now", "Planned next", "Not implemented". Mixing tenses is the most common drift in this repo.
- **No emojis** unless explicitly requested.

## Code And API References

- Reference modules with `path/file.py` (e.g., `gcs_server/ai/context_service.py`).
- Reference functions with `module.function_name()`.
- Reference API routes with the full path (e.g., `POST /api/ai/sessions/{session_id}/intent-test`).
- Use `path/file.py:42` when pointing at a specific line.

## Lists vs Prose

- Bullet lists for parallel items (3+ siblings of the same type).
- Prose for narrative or sequential reasoning.
- Tables when there are 3+ columns or when comparing categories.

Don't make every doc a wall of bullets. Reasoning belongs in prose.

## Folder READMEs

Every folder in `docs/` (excluding `archive/<area>/`) has a `README.md`. It is short, pure navigation:

```markdown
# <Folder Name>

<One paragraph: what this folder holds and how it relates to siblings.>

| Doc | Purpose |
|---|---|
| [requirements.md](./requirements.md) | What the agent must do and why |
| [design.md](./design.md) | Agreed behavior, state machine, contracts |
| [internals/](./internals/) | How the code currently implements it |
```

No tier labels, no metadata, no convention lists. The README points; STYLE.md governs.

## Component Folder Triplet — What Each File Holds

For any component with all three tiers:

**`requirements.md`** — what users / stakeholders need. Locked.
- Goals, success criteria, scope boundaries
- Safety / compliance constraints
- Fixed decisions (with rationale where non-obvious)
- Out-of-scope items, explicitly

**`design.md`** — what the component does, externally. Agreed.
- High-level behavior and state machine
- API surface and contracts with other components
- Events, data shapes, invariants
- Decisions section (component-local; cross-cutting decisions go to an ADR)

**`internals/<topic>.md`** — how the code currently does it. Living.
- Internal modules and their responsibilities
- File paths, function names, code namespaces
- Algorithms, data structures, gotchas
- One concept per file; split when growing past the cap

## When In Doubt

- Smaller is better.
- One file per concept.
- Link instead of duplicate.
- The folder path already says a lot — don't restate it.
- If two docs say the same thing, one is wrong (probably the older one).
- If a convention is missing here, propose adding it before inventing one ad hoc.
