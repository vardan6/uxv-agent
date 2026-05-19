# 0004. LangGraph Planning-Shell Checkpointer: MemorySaver For Now

Date: 2026-05-10
Status: Accepted

## Context

The planning-shell LangGraph graph uses `interrupt()` to pause at the approval and clarification gates. Resuming after an interrupt requires a checkpointer that persists graph state at super-step boundaries.

LangGraph offers several checkpointer implementations:

- `MemorySaver` — in-process, lost on restart
- `SqliteSaver` — single-file SQLite persistence
- `PostgresSaver` — multi-process, durable across restarts
- custom — implementing the checkpoint interface against any backend

The GCS is currently single-process and already runs SQLite for AI sessions and replay. Multi-instance GCS deployment is on the roadmap but not yet a real constraint.

## Decision

Use `MemorySaver` as the planning-shell checkpointer for now. Use stable thread IDs of the form `ai-session:{session_id}:run:{run_id}` so the resume path is deterministic within the lifetime of one process.

## Consequences

- a planning-shell graph in-flight at the moment of GCS restart is lost; the operator must resubmit
- resume across restarts requires switching to a durable checkpointer
- approval and clarification gates work for any session as long as the GCS process stays alive
- a REST fallback exists for both gates so functionality degrades gracefully if the checkpointer is unavailable
- migration to `SqliteSaver` or `PostgresSaver` is a localized change in `graph_runtime.py`; thread-ID format and node logic do not change

## Alternatives Considered

- **`SqliteSaver`.** Reasonable next step. Deferred because the current single-process model does not yet need durability across restart, and adding another SQLite file adds operational surface (backups, schema evolution) without immediate benefit.
- **`PostgresSaver`.** Premature: requires running Postgres, which is not part of the current deployment model. Becomes relevant if/when multi-instance GCS arrives.
- **No checkpointer (REST fallback only).** Rejected: REST fallback is a graceful-degradation path, not the primary mechanism. Without a checkpointer, every interrupt-style operator interaction would require explicit state passing through API calls.

## Follow-Ups

- Switch to `SqliteSaver` when the first user-visible "lost work after restart" report comes in
- Re-evaluate when multi-instance GCS work begins (Implementation Roadmap Priority 5)
