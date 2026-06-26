# ADR 0031 — Headless Full Architecture, Two-Tier State, and a Single Frontend Data Layer

**Status:** Accepted
**Date:** 2026-06-21
**Related:** [ADR 0030](./0030-greenfield-operator-console-frontend.md) (the frontend
stack that consumes this architecture).

## Context

The greenfield operator console (ADR 0030) wants a fully widget-based workspace
where the operator composes any dashboard from a palette of widgets, each
movable / dockable / floatable / popout-able, with multiple instances allowed.
Two requirements make this an architectural decision, not a UI detail:

1. **A widget being present or absent must never change application functionality.**
   No widget may depend on another widget being rendered. If functionality needs
   data another widget would display, it must still obtain that data independently.
2. The product should run **headless** as a *full* application — the web UI is one
   client among future clients (a **CLI** like modern coding agents, and **mobile
   web**). All runtime functionality must live server-side.

Investigation of the backend confirmed it is *already* close to this:
`AppRuntime` (`gcs_server/runtime.py`) is a single app-level singleton owning every
service and store; `MQTTRuntime` ingests telemetry/video and records to
`replay_store` with **zero clients connected**; live state is centralized in
`state_store` and exposed via `/api/snapshot` + WS broadcast. The gap is on the
**frontend**, where each legacy page opens its own WS and holds its own scattered,
DOM-bound copy of state — i.e. state is currently coupled to which page is loaded,
the opposite of requirement 1.

## Decision

### 1. Headless full architecture

The backend is a complete, frontend-agnostic application. All runtime
functionality — MQTT ingest, telemetry recording, control publication, AI agent
execution, mission execution — runs server-side regardless of what is rendered.
Web, future CLI, and mobile are **clients** of the same HTTP/WS contract. The CLI
client (future) serves text-capable features (AI chat, commands, status); it does
not attempt video or map.

### 2. Two-tier state — do not collapse into one namespace

State is deliberately split, and stays split on the backend:

- **Runtime State** — live, ephemeral: telemetry, broker, controller, video.
  Source: `state_store.snapshot()`; transport: pull `/api/snapshot` + WS push.
- **Domain Stores** — persistent: replay sessions, AI sessions, missions,
  operational constraints, agent traces. Source: per-store SQLite; transport: REST.

Forcing persistent domain data into the live snapshot would conflate push-state
with queryable data and bloat the hot path. The two tiers are unified only at the
*frontend access layer*, not on the backend.

### 3. Single frontend data layer (the headline frontend rule)

The frontend has exactly **one** projection of backend state: one WS connection
plus one set of stores that **all** widgets subscribe to. TanStack Query mirrors
the Domain Stores; a WS-fed Zustand store mirrors Runtime State. Adding or removing
a widget must never open/close connections or duplicate state. **Widgets
communicate only through this data layer — never DOM-to-DOM.** This is what makes
isolation, multi-instance, and "no widget depends on another widget" hold.

### 4. Widgets are layout-agnostic views

A widget is a view over the data layer; it owns no authoritative data. All
top-level widgets are isolatable (dock/split/float/popout). Indivisible sub-parts
travel with their widget (OSD overlay bound to its video frame; composer bound to
its chat thread).

### 5. Per-client WS subscription-gating

Backend always *holds* data (snapshot/pull always works), but high-volume push
streams (video, per camera) are **subscribed per mounted widget** — `ws_manager`
holds per-client topic sets (built Slice 5; see `gcs_server/ws.py`). Cheap data
(telemetry, broker) may still broadcast. *Availability* is unconditional;
*streaming* is opt-in. Multi-camera makes this mandatory, not optional.

## Consequences

- The main frontend work of the rewrite is the single data layer, not dockview.
- A small backend addition is required: per-client WS subscriptions (ADR scope is
  the principle; build is a roadmap slice).
- "Operator" identity remains implicit/local for now; multi-user + server-side
  state is deferred. This ADR introduces **no** authentication, consistent with
  GCS requirements §No Authentication Yet.
- Detailed mapping (stores, subscription protocol, window-aware popout rules,
  multi-instance/active-target) lives in
  [`docs/components/gcs/design/operator-console.md`](../../components/gcs/design/operator-console.md).
