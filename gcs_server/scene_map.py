from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


SCENE_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "terrain_scene.v1.json"
DEFAULT_GRID_SIZE = 128


def _to_tuples(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_to_tuples(item) for item in value)
    if isinstance(value, dict):
        return {key: _to_tuples(item) for key, item in value.items()}
    return value


@lru_cache(maxsize=1)
def _load_scene_config() -> dict[str, Any]:
    with SCENE_CONFIG_PATH.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return _to_tuples(payload)


def _sample_manifest_height_grid(heightfield: list[list[float]], grid_size: int) -> tuple[list[list[int]], float, float]:
    source_rows = len(heightfield)
    source_cols = len(heightfield[0]) if source_rows else 0
    if source_rows < 2 or source_cols < 2:
        return [], 0.0, 0.0

    sampled: list[list[float]] = []
    min_h = float("inf")
    max_h = float("-inf")
    for row in range(grid_size):
        src_r = (row / max(1, grid_size - 1)) * (source_rows - 1)
        r0 = max(0, min(source_rows - 2, int(src_r)))
        r1 = r0 + 1
        tr = src_r - r0
        values: list[float] = []
        for col in range(grid_size):
            src_c = (col / max(1, grid_size - 1)) * (source_cols - 1)
            c0 = max(0, min(source_cols - 2, int(src_c)))
            c1 = c0 + 1
            tc = src_c - c0
            h00 = heightfield[r0][c0]
            h01 = heightfield[r0][c1]
            h10 = heightfield[r1][c0]
            h11 = heightfield[r1][c1]
            h = (
                h00 * (1 - tc) * (1 - tr)
                + h01 * tc * (1 - tr)
                + h10 * (1 - tc) * tr
                + h11 * tc * tr
            )
            min_h = min(min_h, h)
            max_h = max(max_h, h)
            values.append(h)
        sampled.append(values)

    span = max(1e-6, max_h - min_h)
    normalized = [
        [int(round(((value - min_h) / span) * 255.0)) for value in row]
        for row in sampled
    ]
    return normalized, min_h, max_h


def _manifest_object_to_map_object(obj: dict[str, Any]) -> dict[str, Any]:
    pos = obj["pose"]["position"]
    geom = obj["geometry"]
    size = {"width": 0.0, "height": 0.0}
    pad_half_extents = {"x": 0.0, "y": 0.0}

    if geom["type"] == "box":
        hx, hy, _hz = geom["half_extents"]
        size = {"width": hx * 2.0, "height": hy * 2.0}
        pad_half_extents = {"x": hx, "y": hy}
    elif geom["type"] == "ellipsoid":
        rx, ry, _rz = geom["radii"]
        size = {"width": rx * 2.0, "height": ry * 2.0}
        pad_half_extents = {"x": rx, "y": ry}
    elif geom["type"] == "compound":
        radius = float(obj.get("metadata", {}).get("footprint_radius", 1.0))
        size = {"width": radius * 2.0, "height": radius * 2.0}
        pad_half_extents = {"x": radius, "y": radius}

    metadata = obj.get("metadata", {})
    return {
        "id": obj["id"],
        "label": metadata.get("label", obj["id"].replace("_", " ").title()),
        "kind": obj["kind"],
        "model_ref": metadata.get("asset_ref", obj["geometry"]["type"]),
        "center": {"x": pos[0], "y": pos[1], "z": pos[2]},
        "size": size,
        "pad_half_extents": pad_half_extents,
        "metadata": metadata,
    }


@lru_cache(maxsize=4)
def get_scene_map_payload(backend: str = "3d-env", grid_size: int = DEFAULT_GRID_SIZE) -> dict[str, Any]:
    if backend != "3d-env":
        raise ValueError(f"Unsupported scene-map backend: {backend}")

    config = _load_scene_config()
    terrain = config["terrain"]
    terrain_size = float(terrain["size"][0])
    grid = max(32, min(256, int(grid_size)))
    heights, min_h, max_h = _sample_manifest_height_grid(terrain["heightfield"], grid)

    half = terrain_size / 2.0
    spawn = config["spawn_points"][0]["pose"]["position"]
    return {
        "backend": backend,
        "source_path": str(SCENE_CONFIG_PATH),
        "coordinate_system": config.get("coordinate_system", {}),
        "terrain_size": terrain_size,
        "tile_count": int(terrain["tile_count"]),
        "bounds": {
            "min_x": -half,
            "max_x": half,
            "min_y": -half,
            "max_y": half,
        },
        "grid_size": grid,
        "height_range": {"min": min_h, "max": max_h},
        "heightmap": heights,
        "roads": [
            {
                "id": road["id"],
                "from": {"x": road["centerline"][0][0], "y": road["centerline"][0][1], "z": road["centerline"][0][2]},
                "to": {"x": road["centerline"][1][0], "y": road["centerline"][1][1], "z": road["centerline"][1][2]},
                "width": road["geometry"]["width"],
            }
            for road in config["roads"]
        ],
        "objects": [_manifest_object_to_map_object(obj) for obj in config["objects"]],
        "spawn": {
            "x": spawn[0],
            "y": spawn[1],
            "z": spawn[2],
        },
    }
