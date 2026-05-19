# 0007. RAG Is Deferred; Live State Stays Structured Only

Date: 2026-05-20
Status: Accepted

## Context

[ADR 0003](./0003-rag-scope-vs-live-context.md) established that RAG covers documents and memory, not live state or geometry. Since then, two questions kept resurfacing in planning:

1. *When* does the RAG layer actually get built?
2. *In the meantime*, what does the AI agent ground on when it needs document-style knowledge?

Several plans (now archived) proposed early RAG work, sometimes scoped to mission history or operator notes. None of these landed, and the AI agent has been operating successfully without RAG by relying on structured live context plus bounded non-RAG retrieval (e.g., explicit document tools, source-controlled prompts).

## Decision

RAG remains the third layer from ADR 0003, but its construction is deferred until after the current AI agent and GCS milestones land. Live state and geometry continue to flow exclusively through structured providers (`AIContextService`, `SpatialQueryService`) — there is no fallback path where live state is served from a vector store.

Until RAG ships, document-style knowledge is delivered via explicit tool calls and source-controlled context windows, not embedded retrieval.

## Consequences

- No vector store, embedding pipeline, or retriever component is added to the runtime in the current phase.
- AI agent code does not contain dead `if rag_enabled` branches; the RAG layer is added as a discrete piece when it lands, not pre-wired.
- Anything that would have wanted RAG (semantic search over mission history, operator-note recall, manual lookup) is either deferred or implemented as a structured tool with a finite catalog.
- This ADR refines, rather than replaces, 0003: scope unchanged, timing made explicit.

## Alternatives Considered

- **Build a thin RAG layer now over docs/ only.** Rejected: the agent works without it, and a thin RAG layer that no tool actually uses is dead weight. Better to land it when there is a concrete consumer.
- **Loosen 0003 and allow RAG over live state during the interim.** Rejected: the numeric/freshness failure modes from 0003 apply regardless of timing.

## Follow-Ups

- When a concrete consumer is named (e.g., "mission history semantic search"), open a new ADR that scopes the RAG implementation and supersedes this timing decision.
