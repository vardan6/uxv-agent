#!/usr/bin/env python3
"""Lightweight validation for the explicit terrain scene manifest."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENE = ROOT / "config" / "terrain_scene.v1.json"


def fail(message: str) -> None:
    raise SystemExit(f"terrain scene validation failed: {message}")


def require_vector(value: object, size: int, label: str) -> None:
    if not isinstance(value, list) or len(value) != size or not all(isinstance(v, (int, float)) for v in value):
        fail(f"{label} must be a {size}-number array")


def validate(scene: dict) -> None:
    if scene.get("schema_version") != "terrain-scene/v1":
        fail("schema_version must be terrain-scene/v1")

    terrain = scene.get("terrain")
    if not isinstance(terrain, dict):
        fail("terrain must be an object")
    heightfield = terrain.get("heightfield")
    tile_count = terrain.get("tile_count")
    if not isinstance(tile_count, int) or tile_count < 2:
        fail("terrain.tile_count must be an integer >= 2")
    if not isinstance(heightfield, list) or len(heightfield) != tile_count:
        fail("terrain.heightfield row count must match tile_count")
    for index, row in enumerate(heightfield):
        if not isinstance(row, list) or len(row) != tile_count:
            fail(f"terrain.heightfield[{index}] column count must match tile_count")
        if not all(isinstance(v, (int, float)) for v in row):
            fail(f"terrain.heightfield[{index}] must contain only numbers")

    ids: set[str] = set()
    for collection_name in ("roads", "objects", "spawn_points"):
        collection = scene.get(collection_name)
        if not isinstance(collection, list):
            fail(f"{collection_name} must be an array")
        for item in collection:
            item_id = item.get("id") if isinstance(item, dict) else None
            if not isinstance(item_id, str) or not item_id:
                fail(f"{collection_name} entries must have non-empty ids")
            if item_id in ids:
                fail(f"duplicate id: {item_id}")
            ids.add(item_id)

    for obj in scene["objects"]:
        pose = obj.get("pose", {})
        require_vector(pose.get("position"), 3, f"{obj['id']}.pose.position")
        require_vector(pose.get("rotation_euler_deg"), 3, f"{obj['id']}.pose.rotation_euler_deg")
        geom = obj.get("geometry")
        if not isinstance(geom, dict) or not isinstance(geom.get("type"), str):
            fail(f"{obj['id']}.geometry.type is required")

    for road in scene["roads"]:
        centerline = road.get("centerline")
        if not isinstance(centerline, list) or len(centerline) < 2:
            fail(f"{road['id']}.centerline must contain at least two points")
        for index, point in enumerate(centerline):
            require_vector(point, 3, f"{road['id']}.centerline[{index}]")


def main() -> None:
    scene_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SCENE
    with scene_path.open("r", encoding="utf-8") as fh:
        scene = json.load(fh)
    validate(scene)
    print(f"terrain scene valid: {scene_path}")


if __name__ == "__main__":
    main()
