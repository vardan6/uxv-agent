# Remote Rover

Remote Rover is a rover-control platform built around two working applications:
- `3d-env/`: a Panda3D-based 3D rover simulator
- `gcs_server/`: a browser-based Ground Control Station (GCS)

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
- [Run And Config Guide](./docs/operations/run-and-config.md)

Subproject documentation:
- [3D Simulator Docs](./docs/3d-env/README.md)
- [GCS Server Docs](./docs/gcs_server/README.md)

## Repository Layout

```text
remote-rover/
  3d-env/
  gcs_server/
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

For cross-platform launcher details, shared config behavior, and telemetry policy notes, use:
- [Run And Config Guide](./docs/operations/run-and-config.md)

## Current Status In One Paragraph

The project is currently a working integrated prototype with a simulator, a browser-based GCS, MQTT-based control and telemetry, and an MQTT-to-WebSocket bootstrap video path. It already supports live control, telemetry, camera streaming, shared runtime configuration, and bandwidth-aware simulator publishing based on active GCS presence. The main remaining work is production hardening: distributed state, security, clearer multi-GCS policy, and a better media transport path.
