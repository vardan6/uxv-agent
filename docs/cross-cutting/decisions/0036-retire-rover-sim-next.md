# 0036. Retire `rover-sim-next`

The ROS 2/Gazebo simulator scaffold is retired. `3d-env` remains the only
supported simulator, and any later simulator direction requires a new decision.

Date: 2026-09-06
Status: Accepted

## Context

ADR 0006 designated `rover-sim-next/` as the eventual successor to `3d-env/`.
The directory remains only a small scaffold: it is not a runnable backend and
nothing in the current runtime imports or launches it. It has received no
meaningful implementation work since May 2026.

Keeping it creates a misleading selectable backend in configuration and settings
interfaces, and leaves future work appearing committed when it is not.

## Decision

Delete `rover-sim-next/` and remove all live references that identify it as a
simulator backend or planned subproject. `3d-env` is the only supported
simulator. No successor simulator is currently planned.

The server must reject an unsupported configured simulator backend with a clear
validation error. It must not silently fall back to `3d-env`.

ADR 0006 is superseded and retained as historical context. Archived planning
snapshots remain unchanged; they describe earlier work, not current direction.

## Consequences

- The GCS, config examples, and tests expose only `3d-env` as a simulator
  backend.
- Existing local or external configuration that still names the retired backend
  fails clearly until it is updated.
- Future simulator work starts with a new ADR; it does not revive this scaffold.
- Live documentation removes the retired path and ROS 2/Gazebo successor plan;
  archive material remains available for traceability.

## Alternatives Considered

- **Keep the scaffold dormant.** Rejected: it presents unsupported software as
  an available backend and retains a commitment the project no longer has.
- **Silently map the old backend name to `3d-env`.** Rejected: it conceals stale
  configuration and can make an operator believe a different simulator is
  running.
- **Copy the scaffold into an archive.** Rejected: Git history preserves it and
  the directory has no independently usable implementation.
