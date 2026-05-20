# Shared Config

This directory stores shared runtime configuration consumed by the simulator and the GCS.

Key files:
- `common.example.json`: tracked safe template
- `common.local.json`: local machine override; do not commit
- `terrain_scene.v1.json`: tracked terrain/object manifest
- `terrain_scene.schema.json`: validation schema

First-time setup:

```bash
cp config/common.example.json config/common.local.json
```

Rules:
- keep real hosts, ports, credentials, and API keys only in `common.local.json`
- never copy those values into tracked docs or tracked config
- treat `terrain_scene.v1.json` as the shared map source for simulator and GCS

More detail:
- `../docs/cross-cutting/operations/run-and-config.md`
- `../docs/components/simulator/internals/terrain-scene.md`
