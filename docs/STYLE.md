# Documentation Style Guide

Conventions for writing and updating Remote Rover documentation. The goal is to keep docs consistent and useful across many incremental sessions.

## Folder Layout

```
docs/
  README.md                 # master catalog (one line per doc)
  STYLE.md                  # this file
  glossary.md               # shared vocabulary
  current-state.md          # living implementation status
  implementation-roadmap.md # living forward plan

  product/                  # what users see / experience / need (PRD + UX)
  technical/                # how things are built (specs)
    architecture.md
    gcs/
    simulator/
    ai/
  decisions/                # ADRs (numbered)
  operations/               # run-and-config and operational guides
  archive/                  # superseded, completed, dated session artifacts
```

## Doc Categories

| Category | Folder | Audience | Contents |
|---|---|---|---|
| Product | `product/` | non-technical, operator, stakeholder | vision, requirements, user-facing UX |
| Technical | `technical/` | developer | architecture, APIs, data models, services |
| Decisions | `decisions/` | both | ADRs — why a non-obvious choice was made |
| Operations | `operations/` | operator + developer | how to run, configure, troubleshoot |
| Living docs | root | both | `current-state.md`, `implementation-roadmap.md` |

If a doc spans multiple categories, split it.

## Naming

- **Use stable concept names**, not session names. `langgraph-design.md`, not `langgraph-design-2026-05-10.md`.
- **No dates in active filenames.** Git history provides dates. Date-stamped filenames belong only in `archive/`.
- **Lowercase, dash-separated.** `operator-experience.md`, not `OperatorExperience.md` or `operator_experience.md`.
- **Singular nouns by default.** `decision`, `provider`, `mode`.

## Cross-Linking

The two-link rule:

- **Every product doc links to its technical counterpart** ("Implementation: see `technical/...`").
- **Every technical doc links back to its product justification** ("Requirements: see `product/...`").

Use relative links from one doc to another. Always link with the `.md` extension.

When introducing a new term, link it to `glossary.md` on first use within a doc.

## Doc Header

Every doc starts with:

```markdown
# Title

## Purpose

One-paragraph statement of why this doc exists and who it serves.

For implementation, see: <link>
For requirements, see: <link>
```

Drop the "For ..." lines if the doc is purely standalone (e.g., `glossary.md`).

## Status In Living Docs

`current-state.md` and `implementation-roadmap.md` change frequently. When updating them:

- include a date heading for new sections (e.g., `### 2026-05-15`)
- when superseding old content, move it to `archive/` rather than deleting
- keep the "Implementation Priority" / "What Works Today" structure stable so readers can predict where to look

## Plans Are Living, Not Permanent

A "plan" doc captures intended future work. When the work is done:

- if the plan content is now description of the implementation, fold it into the matching technical spec
- if the plan content is no longer relevant, archive it

Don't leave executed plans on the active surface.

## Decision Records

ADRs go in `decisions/<number>-<slug>.md`. Numbering is monotonic; never reuse a number.

ADR template:

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

When superseding an ADR, do not delete it — change its status to "Superseded by ..." and add the new ADR.

## Tone And Voice

- **Direct, third-person, present tense.** "The GCS publishes presence" not "The GCS will publish presence" or "We publish presence."
- **No filler praise.** Skip "robust," "comprehensive," "powerful." State what the system does.
- **Distinguish what is from what is planned.** Use clear markers: "Implemented now," "Planned next," "Not implemented." Mixing tenses is the most common drift in this repo.
- **No emojis** unless explicitly requested by the user.

## Code And API References

- Reference modules with `path/file.py` (e.g., `gcs_server/ai/context_service.py`).
- Reference functions with `module.function_name()`.
- Reference API routes with the full path (e.g., `POST /api/ai/sessions/{session_id}/intent-test`).
- Use file_path:line_number when pointing at a specific line.

## Lists vs Prose

- Use bullet lists for parallel items (3+ siblings of the same type).
- Use prose for narrative or sequential reasoning.
- Use tables when there are 3+ columns or when comparing categories.

Don't make every doc a wall of bullets. Reasoning belongs in prose.

## Updating The Catalog

When adding a new doc, add a one-line entry to `README.md` under the right section. When archiving, remove the entry. The README is the source of truth for what is "active" — if a doc is not in the README, it is dead weight.

## When In Doubt

- Smaller is better.
- One file per concept.
- Link instead of duplicate.
- If two docs say the same thing, one is wrong (probably the older one).
