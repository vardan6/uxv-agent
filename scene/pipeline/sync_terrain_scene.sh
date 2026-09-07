#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

python3 scene/pipeline/generate_terrain_scene.py
python3 scene/pipeline/validate_terrain_scene.py
python3 -m py_compile \
  scene/pipeline/generate_terrain_scene.py \
  scene/pipeline/validate_terrain_scene.py \
  3d-env/simulator/terrain.py \
  3d-env/simulator/main.py \
  scene/scene_map.py \
  gcs_server/ai/road_graph_service.py

python3 - <<'PY'
from scene.scene_map import get_scene_map_payload
from gcs_server.ai.road_graph_service import RoadGraphService

scene = get_scene_map_payload(grid_size=64)
graph = RoadGraphService()

print(
    "scene map smoke:",
    f"objects={len(scene['objects'])}",
    f"roads={len(scene['roads'])}",
    f"grid={scene['grid_size']}",
    f"height_range={scene['height_range']['min']:.2f}..{scene['height_range']['max']:.2f}",
)
print(
    "road graph smoke:",
    f"nodes={graph.node_count}",
    f"edges={graph.edge_count}",
)
PY

echo "terrain scene synced and validated"
