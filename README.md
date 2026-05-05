# Remote Rover

Remote Rover is a rover-control platform built around two working applications:
- `3d-env/`: a Panda3D-based 3D rover simulator
- `gcs_server/`: a browser-based Ground Control Station (GCS)

It also contains `rover-sim-next/`, the scaffold for the planned ROS 2 + Gazebo successor simulator.

The high-level goal is broader than the current rover simulator: build a remote operations stack for rovers and later other robots. The current rover-in-simulator workflow is the prototype path toward real remotely controlled robots, where users can operate directly or ask AI agents by text or voice to generate missions, monitor execution, and escalate to a human when the robot encounters unexpected conditions.

The system already supports the full working control loop:
- browser control through the GCS
- MQTT control delivery to the simulator
- simulator telemetry publication
- simulator camera-frame publication
- browser telemetry and camera display through the GCS
- simulator-side outbound publish suppression when no active GCS is present

## Documentation

Main documentation entry point:
- [Documentation Portal](./docs/README.md)

Recommended reading order:
- [Project Overview](./docs/project-overview.md)
- [Current State](./docs/current-state.md)
- [Architecture](./docs/architecture.md)
- [Implementation Roadmap](./docs/implementation-roadmap.md)
- [AI Agent, LLM Provider, LangGraph, And RAG Implementation Plan](./docs/ai-agent-rag-implementation-plan.md)
- [Run And Config Guide](./docs/operations/run-and-config.md)

Subproject documentation:
- [3D Simulator Docs](./docs/3d-env/README.md)
- [GCS Server Docs](./docs/gcs_server/README.md)
- [Terrain Scene Manifest](./docs/terrain-scene.md)

## Repository Layout

```text
remote-rover/
  3d-env/
  gcs_server/
  rover-sim-next/
  config/
  docs/
```

## Quick Start

Run the GCS:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
pip install -r gcs_server/requirements-gcs.txt
python -m gcs_server
```

Run the simulator:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover/3d-env
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python simulator/main.py
```

Regenerate the explicit terrain scene manifest when terrain/object definitions change:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
python3 tools/generate_terrain_scene.py
python3 tools/validate_terrain_scene.py
```

For cross-platform launcher details, shared config behavior, and telemetry policy notes, use:
- [Run And Config Guide](./docs/operations/run-and-config.md)

## Current Status In One Paragraph

The project is currently a working integrated prototype with a Panda3D simulator, a browser-based GCS, MQTT-based control and telemetry, GCS-side replay, a first replay map, and an MQTT-to-WebSocket bootstrap video path. A major project target is AI-assisted remote robot operation: an operator prompts by text or voice, external AI agents generate a mission using map and robot context, the mission is passed to an autopilot/control layer, and AI agents monitor execution in parallel. If new obstacles, map mismatches, sensor findings, or other rule-triggering events make the mission unsafe or impossible, the agents either adjust within approved policy or report to a human for a revised prompt or decision. The first GCS-side AI foundation now exists through LLM provider settings, provider checks, model routing, and selected-section JSON settings import/export. The next AI implementation track is provider-backed chat, AI sessions, mission generation, supervised rover-intent parsing, and later LangGraph/RAG-backed mission monitoring and planning. `rover-sim-next` is scaffolded but not yet a working backend, and remains the next major simulator-platform milestone.
