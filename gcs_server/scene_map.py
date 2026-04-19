from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any


SCENE_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "terrain_scene.json"
DEFAULT_GRID_SIZE = 128


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _smoothstep(edge0: float, edge1: float, x: float) -> float:
    if edge0 == edge1:
        return 0.0
    t = _clamp((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _dist_point_to_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> tuple[float, float]:
    abx = bx - ax
    aby = by - ay
    apx = px - ax
    apy = py - ay
    denom = abx * abx + aby * aby
    if denom <= 1e-9:
        return math.hypot(px - ax, py - ay), 0.0
    t = _clamp((apx * abx + apy * aby) / denom, 0.0, 1.0)
    cx = ax + t * abx
    cy = ay + t * aby
    return math.hypot(px - cx, py - cy), t


def _rect_loop_points(cx: float, cy: float, hx: float, hy: float) -> list[tuple[float, float]]:
    return [
        (cx - hx, cy - hy),
        (cx + hx, cy - hy),
        (cx + hx, cy + hy),
        (cx - hx, cy + hy),
        (cx - hx, cy - hy),
    ]


def _polyline_segments(points: list[tuple[float, float]]) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    return [(points[i], points[i + 1]) for i in range(len(points) - 1)]


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


def _road_segments(scene_layout: dict[str, Any]) -> list[tuple[tuple[float, float], tuple[float, float], float, float]]:
    pa = scene_layout["plant_a"]
    pb = scene_layout["plant_b"]
    bld = scene_layout["building"]
    hub = scene_layout["start_hub"]

    loop_a = _rect_loop_points(*pa["center"], *pa["loop_half_extents"])
    loop_b = _rect_loop_points(*pb["center"], *pb["loop_half_extents"])

    connect_plants = [
        (pa["center"][0], pa["center"][1] + pa["loop_half_extents"][1]),
        (0.0, 36.0),
        (pb["center"][0], pb["center"][1] - pb["loop_half_extents"][1]),
    ]
    connect_building_a = [
        bld["center"],
        (-46.0, -38.0),
        (pa["center"][0] + pa["loop_half_extents"][0], pa["center"][1]),
    ]
    connect_building_b = [
        bld["center"],
        (44.0, 34.0),
        (pb["center"][0] - pb["loop_half_extents"][0], pb["center"][1]),
    ]
    connect_start_hub = [
        hub["center"],
        (0.0, 8.0),
        bld["center"],
    ]

    segments = []

    for p0, p1 in _polyline_segments(loop_a):
        segments.append((p0, p1, pa["floor_z"], pa["floor_z"]))
    for p0, p1 in _polyline_segments(loop_b):
        segments.append((p0, p1, pb["floor_z"], pb["floor_z"]))

    plant_connector_nodes = [
        (connect_plants[0], pa["floor_z"]),
        (connect_plants[1], -2.3),
        (connect_plants[2], pb["floor_z"]),
    ]
    for i in range(len(plant_connector_nodes) - 1):
        (p0, z0) = plant_connector_nodes[i]
        (p1, z1) = plant_connector_nodes[i + 1]
        segments.append((p0, p1, z0, z1))

    a_nodes = [
        (connect_building_a[0], bld["floor_z"]),
        (connect_building_a[1], -2.5),
        (connect_building_a[2], pa["floor_z"]),
    ]
    b_nodes = [
        (connect_building_b[0], bld["floor_z"]),
        (connect_building_b[1], -2.2),
        (connect_building_b[2], pb["floor_z"]),
    ]
    for nodes in (a_nodes, b_nodes):
        for i in range(len(nodes) - 1):
            (p0, z0) = nodes[i]
            (p1, z1) = nodes[i + 1]
            segments.append((p0, p1, z0, z1))

    hub_nodes = [
        (connect_start_hub[0], hub["floor_z"]),
        (connect_start_hub[1], -1.2),
        (connect_start_hub[2], bld["floor_z"]),
    ]
    for i in range(len(hub_nodes) - 1):
        (p0, z0) = hub_nodes[i]
        (p1, z1) = hub_nodes[i + 1]
        segments.append((p0, p1, z0, z1))

    return segments


def _gaussian_2d(x: float, y: float, cx: float, cy: float, sigma: float) -> float:
    dx = x - cx
    dy = y - cy
    d2 = dx * dx + dy * dy
    return math.exp(-d2 / (2.0 * sigma * sigma))


def _base_height(
    x: float,
    y: float,
    terrain_size: float,
    valleys: tuple[tuple[float, float, float, float], ...],
    hills: tuple[tuple[float, float, float, float], ...],
) -> float:
    xn = x / terrain_size
    yn = y / terrain_size

    h = 0.0
    h += math.sin(xn * 7.0 + 0.8) * math.cos(yn * 5.8 - 0.6) * 1.7
    h += math.sin(xn * 13.0 + 2.1) * math.cos(yn * 11.2 + 0.9) * 1.3
    h += math.sin(xn * 24.0 - 1.0) * math.sin(yn * 21.4 + 0.4) * 0.55

    for cx, cy, sigma, amp in valleys:
        h -= amp * _gaussian_2d(x, y, cx, cy, sigma)

    for cx, cy, sigma, amp in hills:
        h += amp * _gaussian_2d(x, y, cx, cy, sigma)

    return h


def _apply_flatten_pads(x: float, y: float, h: float, scene_layout: dict[str, Any]) -> float:
    specs = [
        scene_layout["plant_a"],
        scene_layout["plant_b"],
        scene_layout["building"],
        scene_layout["start_hub"],
    ]
    for spec in specs:
        cx, cy = spec["center"]
        hx, hy = spec["pad_half_extents"]
        nx = (x - cx) / max(1e-5, hx)
        ny = (y - cy) / max(1e-5, hy)
        d = math.sqrt(nx * nx + ny * ny)
        inner = _smoothstep(1.15, 0.80, d)
        if inner > 0.0:
            h = h * (1.0 - inner) + spec["floor_z"] * inner

        sh = spec.get("surround_half_extents")
        if sh:
            shx, shy = sh
            snx = (x - cx) / max(1e-5, shx)
            sny = (y - cy) / max(1e-5, shy)
            sd = math.sqrt(snx * snx + sny * sny)
            surround = _smoothstep(1.28, 0.82, sd)
            if surround > 0.0:
                h = h * (1.0 - surround * 0.82) + spec["floor_z"] * (surround * 0.82)
    return h


def _apply_flatten_roads(
    x: float,
    y: float,
    h: float,
    scene_layout: dict[str, Any],
    road_segments: list[tuple[tuple[float, float], tuple[float, float], float, float]],
) -> float:
    road_width = scene_layout["roads"]["width"]
    feather = scene_layout["roads"]["feather"]

    best_dist = 1e9
    best_target = h
    for (p0, p1, z0, z1) in road_segments:
        dist, t = _dist_point_to_segment(x, y, p0[0], p0[1], p1[0], p1[1])
        if dist < best_dist:
            best_dist = dist
            best_target = z0 + (z1 - z0) * t

    blend = _smoothstep(feather, road_width, best_dist)
    if blend > 0.0:
        h = h * (1.0 - blend * 0.92) + best_target * (blend * 0.92)
    return h


def _height_at(
    x: float,
    y: float,
    terrain_size: float,
    scene_layout: dict[str, Any],
    valleys: tuple[tuple[float, float, float, float], ...],
    hills: tuple[tuple[float, float, float, float], ...],
    road_segments: list[tuple[tuple[float, float], tuple[float, float], float, float]],
) -> float:
    h = _base_height(x, y, terrain_size, valleys, hills)
    h = _apply_flatten_pads(x, y, h, scene_layout)
    h = _apply_flatten_roads(x, y, h, scene_layout, road_segments)
    return h


def _sample_height_grid(
    terrain_size: float,
    scene_layout: dict[str, Any],
    valleys: tuple[tuple[float, float, float, float], ...],
    hills: tuple[tuple[float, float, float, float], ...],
    road_segments: list[tuple[tuple[float, float], tuple[float, float], float, float]],
    grid_size: int,
) -> tuple[list[list[int]], float, float]:
    half = terrain_size / 2.0
    heights: list[list[float]] = []
    min_h = float("inf")
    max_h = float("-inf")
    for row in range(grid_size):
        y = -half + (row / max(1, grid_size - 1)) * terrain_size
        values: list[float] = []
        for col in range(grid_size):
            x = -half + (col / max(1, grid_size - 1)) * terrain_size
            h = _height_at(x, y, terrain_size, scene_layout, valleys, hills, road_segments)
            min_h = min(min_h, h)
            max_h = max(max_h, h)
            values.append(h)
        heights.append(values)

    span = max(1e-6, max_h - min_h)
    normalized = [
        [int(round(((value - min_h) / span) * 255.0)) for value in row]
        for row in heights
    ]
    return normalized, min_h, max_h


def _build_objects(scene_layout: dict[str, Any]) -> list[dict[str, Any]]:
    objects = []
    for key in ("plant_a", "plant_b", "building", "start_hub"):
        spec = scene_layout[key]
        hx, hy = spec["pad_half_extents"]
        cx, cy = spec["center"]
        objects.append({
            "id": key,
            "label": spec.get("label", key.replace("_", " ").title()),
            "kind": spec.get("kind", "landmark"),
            "model_ref": spec.get("model_ref", key),
            "center": {"x": cx, "y": cy, "z": spec["floor_z"]},
            "size": {"width": hx * 2.0, "height": hy * 2.0},
            "pad_half_extents": {"x": hx, "y": hy},
        })
    return objects


@lru_cache(maxsize=4)
def get_scene_map_payload(backend: str = "3d-env", grid_size: int = DEFAULT_GRID_SIZE) -> dict[str, Any]:
    if backend != "3d-env":
        raise ValueError(f"Unsupported scene-map backend: {backend}")

    config = _load_scene_config()
    terrain_size = float(config["terrain_size"])
    scene_layout = config["scene_layout"]
    valleys = config["valleys"]
    hills = config["hills"]
    road_segments = _road_segments(scene_layout)
    grid = max(32, min(256, int(grid_size)))
    heights, min_h, max_h = _sample_height_grid(
        terrain_size,
        scene_layout,
        valleys,
        hills,
        road_segments,
        grid,
    )

    half = terrain_size / 2.0
    return {
        "backend": backend,
        "source_path": str(SCENE_CONFIG_PATH),
        "terrain_size": terrain_size,
        "tile_count": int(config["tile_count"]),
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
                "from": {"x": p0[0], "y": p0[1], "z": z0},
                "to": {"x": p1[0], "y": p1[1], "z": z1},
            }
            for p0, p1, z0, z1 in road_segments
        ],
        "objects": _build_objects(scene_layout),
        "spawn": {
            "x": scene_layout["spawn"]["xy"][0],
            "y": scene_layout["spawn"]["xy"][1],
        },
    }
