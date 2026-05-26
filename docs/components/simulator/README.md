# Simulator Component

The simulator is the vehicle-side runtime. It provides a simulated rover with physics and terrain interaction, MQTT control intake, telemetry generation, and simulated camera output.

Two simulator implementations exist:
- **`3d-env/`** — current working baseline (Panda3D + Bullet)
- **`rover-sim-next/`** — ROS 2 + Gazebo scaffolded side path (not part of the working runtime)

## Documentation Tier

| Tier | File | Status |
|---|---|---|
| Requirements | [requirements.md](./requirements.md) | Complete |
| Design | [design.md](./design.md) | Complete |
| Internals | [internals/](./internals/) | Complete |

## Internals Index

| File | Topic |
|---|---|
| [terrain-scene.md](./internals/terrain-scene.md) | Terrain scene manifest format, generation, and pipeline |
| [technical-details.md](./internals/technical-details.md) | MQTT integration details, publish gating, rover runtime baseline |
| [rover-physics-tuning.md](./internals/rover-physics-tuning.md) | Physics tuning method, accepted parameter baseline, test sequence |
| [rover-sim-next-phase-1.md](./internals/rover-sim-next-phase-1.md) | Phase 1 implementation checklist for `rover-sim-next` |
| [shadow-enhancement.md](./internals/shadow-enhancement.md) | Shadow quality implementation: tiers, fixes applied, deferred work |

## Code Locations

- `3d-env/` — current Panda3D simulator
- `rover-sim-next/` — ROS 2 + Gazebo scaffolded side path
- `config/terrain_scene.v1.json` — canonical scene manifest
- `config/common.example.json` — shared MQTT/GCS config contract
