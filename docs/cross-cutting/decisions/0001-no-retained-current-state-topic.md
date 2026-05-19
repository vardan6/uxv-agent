# 0001. No Retained MQTT Current-State Topic

Date: 2026-05-09
Status: Accepted

## Context

The AI Chat layer needs exact, low-latency access to the rover's current state, runtime status, controller state, and other live facts. An obvious option is to publish a retained MQTT topic with the current rover state so any consumer (including AI services) can subscribe and get the latest snapshot from the broker.

The single-process GCS already receives all telemetry and owns browser/runtime state. It is also where AI Chat runs. Publishing a separate retained current-state topic would duplicate facts the GCS already holds.

## Decision

Do not publish a retained MQTT current-state topic. Keep MQTT as the telemetry/control transport only. Make the GCS the first current-state owner: AI Chat reads exact live facts from in-process structured providers (`AIContextService`, `SpatialQueryService`), not from the broker.

## Consequences

- AI Chat and Agent mode get exact live facts without a second subscription path
- No new retained topic to define, version, or coordinate across producers
- A single-process GCS is the bottleneck for current-state ownership today
- Multi-instance GCS deployments will need a shared state backend (Redis or equivalent) before they can share live state across processes
- RAG is reserved for documents, reports, definitions, mission history, operator notes — not exact live state or map geometry

## Alternatives Considered

- **Retained MQTT current-state topic.** Rejected: duplicates facts already held by the GCS, adds a new schema to maintain, complicates multi-producer coordination, and does not solve the multi-instance GCS problem (a retained topic is a snapshot, not a coordination primitive).
- **Vector RAG over telemetry.** Rejected: exact numeric facts (pose, distances, freshness) should not be approximated through embedding similarity.
- **Direct broker subscription from the AI service.** Rejected: the GCS already holds the freshest snapshot; another subscriber would race against it without benefit.

## Follow-Ups

- A shared state backend (e.g., Redis) becomes necessary if multiple GCS instances must coordinate live state. See [Implementation Roadmap](../../implementation-roadmap.md) Priority 5.
