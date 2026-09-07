# Simulator Component

The simulator is the vehicle-side runtime. It provides a simulated rover with physics and terrain interaction, MQTT control intake, telemetry generation, and simulated camera output.

The sole supported simulator is **`3d-env/`**, the current Panda3D + Bullet baseline. Any successor direction requires a new ADR.

## Documentation Tier

| Tier | File | Status |
|---|---|---|
| Requirements | [requirements.md](./requirements.md) | Complete |
| Design (overview) | [design.md](./design.md) | Complete |
| Design (per topic) | [design/*.md](./design/) — terrain-scene, technical-details, rover-physics-tuning, shadow-enhancement | Complete |

`design/` files share the same stability tier as `design.md` — topic organization, not a separate tier.

## Code Locations

- `3d-env/` — current Panda3D simulator
- `scene/scenes/terrain_scene.v1.json` — canonical scene manifest
- `config/common.example.json` — shared MQTT/GCS config contract
