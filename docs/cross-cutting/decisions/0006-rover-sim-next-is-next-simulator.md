# 0006. `rover-sim-next` Is The Next Simulator Implementation

Date: 2026-05-20
Status: Accepted

## Context

The current simulator (`3d-env/`, see [0005](./0005-keep-3d-env-as-current-simulator.md)) is a browser-only Three.js application. It has known limitations: physics fidelity is rough, the simulation is tied to a browser window, headless / batch runs are awkward, and the rover model is not driven from a shared robotics description.

Several candidate replacements were sketched at different times: a Unity-based simulator, a Gazebo classic setup, and an isaac-sim path. None landed. The repository currently contains `rover-sim-next/`, which is a URDF + Gazebo-style scaffold intended to address the limitations above.

## Decision

`rover-sim-next/` is the next simulator implementation. When the current simulator is replaced, it is replaced by `rover-sim-next`, not by a new third option.

Work on `rover-sim-next` is sequenced after the current high-priority AI agent and GCS milestones — it does not block them, but it is the named successor when simulator work resumes.

## Consequences

- Documentation about future simulator capability (physics tuning, headless mode, shared URDF) targets `rover-sim-next` by name, not a generic "future simulator."
- `components/simulator/design.md` includes a "planned" section describing the `rover-sim-next` direction; `design.md` tracks the implementation as it lands.
- New simulator capability work that does not fit in `3d-env` lands in `rover-sim-next/` rather than as a third scaffold.
- If `rover-sim-next` is abandoned, this ADR is superseded; it is not edited.

## Alternatives Considered

- **Leave the next-simulator slot open.** Rejected: the ambiguity caused repeated relitigation in past planning sessions. Naming the successor removes that overhead.
- **Pick Unity / Isaac / Gazebo-classic.** Rejected at earlier dates; not revisiting here. Captured for traceability in the archived planning notes under `archive/simulator/`.

## Follow-Ups

- A cutover ADR will be written when `rover-sim-next` reaches parity and replaces `3d-env`.
- Features that still wait for `rover-sim-next`: see
  [ADR 0026](./0026-replay-session-logging-ships-scrubbing-replay-deferred.md).
