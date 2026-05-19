# 0003. RAG Scope: Documents And Memory, Not Live State

Date: 2026-05-09
Status: Accepted

## Context

The AI layer needs to ground responses in real project knowledge. Two broad approaches exist:

1. Retrieve everything via RAG (rover state, telemetry, scene, docs, mission history) — uniform retrieval interface
2. Split into two tiers: structured live context for exact facts; RAG for semantic/document knowledge

The first approach is simpler but has well-known failure modes for numeric and geometric data: embedding similarity does not preserve numeric precision, distances and counts can be approximated incorrectly, freshness semantics are lost.

## Decision

Use three explicit knowledge layers:

```text
Current state layer
  -> latest rover pose, heading, speed, freshness, controller, active mission
  -> exact structured data from GCS runtime and telemetry

Spatial world model
  -> static terrain/map objects and later dynamic detected objects
  -> exact geometric queries from a structured map/perception store

RAG knowledge layer
  -> project docs, manuals, definitions, mission history, reports, operator notes
  -> semantic retrieval with citations
```

RAG is reserved for the third layer. Live state and geometry never go through RAG.

## Consequences

- exact numeric answers (distances, headings, counts) are computed by the backend from authoritative data
- the model chooses which tool to call; the backend computes the answer
- two retrieval paths to maintain (structured providers + RAG) instead of one
- the always-on context can stay compact because larger details are tool-fetched rather than retrieved-and-stuffed
- a future perception layer (camera, lidar, IR, ultrasonic) integrates as structured detected objects in the spatial world model, not as raw blobs in RAG
- citations and source tracking only need to exist for the RAG layer

## Alternatives Considered

- **Pure RAG.** Rejected: numeric/geometric loss, freshness loss, no clear way to enforce "exact" vs "semantic" answers.
- **Pure structured.** Rejected: project docs, mission history, operator notes, and free-form knowledge benefit from semantic retrieval; coercing them into structured fields loses information.
- **Two layers (structured + RAG, no separate spatial layer).** Considered. The spatial layer is essentially structured data, but it has enough domain-specific concerns (geometry, sectors, route intersection) that calling it out separately keeps the structured layer focused on state rather than computation.

## Follow-Ups

- RAG layer is not yet implemented; Phase 4 delivered bounded non-RAG retrieval/source controls first, and true RAG remains a later AI phase
- Perception tool contract (Phase 6) will define how dynamic detected objects flow into the spatial world model
