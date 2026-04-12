# Remote Rover Documentation

This directory is the main documentation set for the `remote-rover` workspace.

It is organized for two audiences:
- non-technical readers who need to understand what the project does, what is already working, and what is planned next
- technical readers who need architecture, runtime contracts, operational notes, and subproject details

## Start Here

- [Project Overview](./project-overview.md): high-level explanation of the project, intended use, and current demo story
- [Current State](./current-state.md): what is implemented now, what is partially implemented, and the main current limitations
- [Architecture](./architecture.md): how the simulator, GCS, broker, and shared config fit together
- [Implementation Roadmap](./implementation-roadmap.md): recommended forward plan, grouped by priority
- [Simulation Platform Requirements](./simulation-platform-requironments.md): stable requirements baseline for the next simulator and replay/map/logging work
- [Simulation Platform Plan](./simulation-platform-plan.md): current implementation and remaining phases for the simulator transition
- [rover-sim-next Phase 1 Checklist](./rover-sim-next-phase-1-checklist.md): concrete first implementation checklist by file and module for the successor simulator
- [Run And Config Guide](./operations/run-and-config.md): how to run the simulator and GCS, and where runtime configuration lives

## Subproject Documents

- [3D Simulator Docs](./3d-env/README.md): simulator purpose, features, controls, telemetry publishing policy, and technical structure
- [GCS Server Docs](./gcs_server/README.md): Ground Control Station purpose, browser workflow, MQTT integration, and technical structure
- [rover-sim-next Scaffold](/mnt/c/Users/vardana/Documents/Proj/remote-rover/rover-sim-next/README.md): current successor-simulator scaffold and intended ROS 2 + Gazebo direction

## Existing Historical Documents

Older planning and phase documents are still kept in the repository for historical traceability, but they should not be treated as the main source of truth for the current system.

Historical references:
- `3d-env/phase1-3D-Simulator.md`
- `3d-env/initial-hl-design.md`
- `3d-env/mqtt-plan-canonical-2026-04-05_00-58-36.md`
- `PROJECT_REVIEW_AND_CURRENT_STATE.md`
- `remote_rover_architecture_and_implementation_plan.md`

For presentation and onboarding, use this `docs/` directory first.
