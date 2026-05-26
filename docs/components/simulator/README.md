# Simulator Component

The simulator is the vehicle-side runtime. It provides a simulated rover with physics and terrain interaction, MQTT control intake, telemetry generation, and simulated camera output.

Two simulator implementations exist:
- **`3d-env/`** — current working baseline (Panda3D + Bullet)
- **`rover-sim-next/`** — ROS 2 + Gazebo scaffolded side path (not part of the working runtime)

## Documentation Tier

| Tier | File | Status |
|---|---|---|
| Requirements | [requirements.md](./requirements.md) | Complete |
| Design (overview) | [design.md](./design.md) | Complete |
| Design (per topic) | [design/*.md](./design/) — terrain-scene, technical-details, rover-physics-tuning, rover-sim-next-phase-1, shadow-enhancement | Complete |

`design/` files share the same stability tier as `design.md` — topic organization, not a separate tier.

## Code Locations

- `3d-env/` — current Panda3D simulator
- `rover-sim-next/` — ROS 2 + Gazebo scaffolded side path
- `config/terrain_scene.v1.json` — canonical scene manifest
- `config/common.example.json` — shared MQTT/GCS config contract
