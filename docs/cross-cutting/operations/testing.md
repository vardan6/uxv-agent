# Repository Testing

This guide defines the repository-owned fast and full verification layers. It
covers suite membership, budgets, and environment-gated reporting; focused
commands used while developing remain useful subsets, not additional layers.

## Fast Deterministic Suite

`./bin/test-fast` is the routine gate that coding agents may run before and
after a small change. It must be offline, deterministic, non-destructive, and
independent of browsers, brokers, GPUs, Qdrant, model downloads, external
providers, and hardware.

The target budget is 30 seconds on the current machine, excluding one-time
dependency installation. The suite includes:

- all backend pytest tests;
- all legacy-map Node tests;
- scene validation and scene-reader contract tests;
- Python compilation for every Python project;
- shell syntax checks for active launchers; and
- pure tests added for scene, simulator utilities, MAV simulator protocol and
  lifecycle behavior, RAG, and TTS.

The full React suite is excluded while mounted-filesystem startup keeps it over
the budget. Individual React tests remain valid focused checks. If eligible
tests later exceed the budget, improve execution or the environment rather than
silently moving deterministic coverage out of this layer.

The script must use the supported root Python environment, set imports
explicitly, print readable phase labels, document its underlying commands, and
return nonzero when any member fails. It must not modify tracked files.

## Full Branch And Merge Suite

`./bin/test-full` is the complete gate after a large implementation, again
after material review fixes, and before merge. Its automated target budget is
five minutes on the current machine, excluding intentional model downloads and
hardware or SITL checks.

It includes the fast suite plus:

- the complete React Vitest suite and production build;
- backend and frontend coverage reports once their tooling is installed;
- FastAPI application and API integration tests;
- disposable-service RAG integration with fake embeddings and optional
  disposable Qdrant;
- TTS, `mav-sim`, and headless `3d-env` startup checks where supported;
- browser checks for map and mission workflows, docking, and popouts;
- GCS-to-simulator MQTT telemetry, video, and control checks where supported;
  and
- Git whitespace checks plus confirmation that generators did not unexpectedly
  modify tracked artifacts.

Every environment-gated check must report pass, fail, or skipped with a reason.
Silent omission is not success. For the current restructure, both renamed map
consumers and the browser map and mission workflows are mandatory acceptance
checks; broker, GPU, model, simulator, SITL, and hardware checks may skip when
their prerequisite is unavailable and the reason is recorded.

## Adoption Sequence

Restore canonical backend test collection first, then add `./bin/test-fast`.
Those two changes gate further restructure implementation. The full gate,
coverage tooling, and the existing frontend build repairs must land before the
restructure PR merges. Broader missing product tests proceed as independent
slices and do not block the restructure.

The evidence and gap inventory behind this policy are recorded in the
[2026-09-07 testing audit](../../reviews/testing-audit-2026-09-07.md).
