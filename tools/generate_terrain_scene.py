#!/usr/bin/env python3
"""Generate the explicit terrain scene manifest from the legacy compact config."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LEGACY_CONFIG = ROOT / "config" / "terrain_scene.json"
OUTPUT = ROOT / "config" / "terrain_scene.v1.json"


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def smoothstep(edge0: float, edge1: float, x: float) -> float:
    if edge0 == edge1:
        return 0.0
    t = clamp((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def dist_point_to_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> tuple[float, float]:
    abx = bx - ax
    aby = by - ay
    apx = px - ax
    apy = py - ay
    denom = abx * abx + aby * aby
    if denom <= 1e-9:
        return math.hypot(px - ax, py - ay), 0.0
    t = clamp((apx * abx + apy * aby) / denom, 0.0, 1.0)
    cx = ax + t * abx
    cy = ay + t * aby
    return math.hypot(px - cx, py - cy), t


def rect_loop_points(cx: float, cy: float, hx: float, hy: float) -> list[list[float]]:
    return [
        [cx - hx, cy - hy],
        [cx + hx, cy - hy],
        [cx + hx, cy + hy],
        [cx - hx, cy + hy],
        [cx - hx, cy - hy],
    ]


def polyline_segments(points: list[list[float]]) -> list[tuple[list[float], list[float]]]:
    return [(points[i], points[i + 1]) for i in range(len(points) - 1)]


def road_segments(scene_layout: dict[str, Any]) -> list[dict[str, Any]]:
    pa = scene_layout["plant_a"]
    pb = scene_layout["plant_b"]
    bld = scene_layout["building"]
    hub = scene_layout["start_hub"]

    loop_a = rect_loop_points(*pa["center"], *pa["loop_half_extents"])
    loop_b = rect_loop_points(*pb["center"], *pb["loop_half_extents"])
    connect_plants = [
        [pa["center"][0], pa["center"][1] + pa["loop_half_extents"][1]],
        [0.0, 36.0],
        [pb["center"][0], pb["center"][1] - pb["loop_half_extents"][1]],
    ]
    connect_building_a = [
        bld["center"],
        [-46.0, -38.0],
        [pa["center"][0] + pa["loop_half_extents"][0], pa["center"][1]],
    ]
    connect_building_b = [
        bld["center"],
        [44.0, 34.0],
        [pb["center"][0] - pb["loop_half_extents"][0], pb["center"][1]],
    ]
    connect_start_hub = [
        hub["center"],
        [0.0, 8.0],
        bld["center"],
    ]

    roads: list[dict[str, Any]] = []

    def add_segment(road_id: str, p0: list[float], p1: list[float], z0: float, z1: float) -> None:
        roads.append({
            "id": road_id,
            "kind": "road",
            "geometry": {"type": "corridor", "width": scene_layout["roads"]["width"], "feather": scene_layout["roads"]["feather"]},
            "centerline": [[round(p0[0], 6), round(p0[1], 6), round(z0, 6)], [round(p1[0], 6), round(p1[1], 6), round(z1, 6)]],
            "metadata": {"drivable": True, "route_planning_cost": "preferred"},
        })

    for idx, (p0, p1) in enumerate(polyline_segments(loop_a)):
        add_segment(f"road_plant_a_loop_{idx}", p0, p1, pa["floor_z"], pa["floor_z"])
    for idx, (p0, p1) in enumerate(polyline_segments(loop_b)):
        add_segment(f"road_plant_b_loop_{idx}", p0, p1, pb["floor_z"], pb["floor_z"])

    for prefix, nodes in (
        ("road_plants_connector", [(connect_plants[0], pa["floor_z"]), (connect_plants[1], -2.3), (connect_plants[2], pb["floor_z"])]),
        ("road_building_to_plant_a", [(connect_building_a[0], bld["floor_z"]), (connect_building_a[1], -2.5), (connect_building_a[2], pa["floor_z"])]),
        ("road_building_to_plant_b", [(connect_building_b[0], bld["floor_z"]), (connect_building_b[1], -2.2), (connect_building_b[2], pb["floor_z"])]),
        ("road_start_hub_to_building", [(connect_start_hub[0], hub["floor_z"]), (connect_start_hub[1], -1.2), (connect_start_hub[2], bld["floor_z"])]),
    ):
        for idx in range(len(nodes) - 1):
            p0, z0 = nodes[idx]
            p1, z1 = nodes[idx + 1]
            add_segment(f"{prefix}_{idx}", p0, p1, z0, z1)

    return roads


def gaussian_2d(x: float, y: float, cx: float, cy: float, sigma: float) -> float:
    dx = x - cx
    dy = y - cy
    return math.exp(-(dx * dx + dy * dy) / (2.0 * sigma * sigma))


def base_height(x: float, y: float, terrain_size: float, valleys: list[list[float]], hills: list[list[float]]) -> float:
    xn = x / terrain_size
    yn = y / terrain_size
    h = 0.0
    h += math.sin(xn * 7.0 + 0.8) * math.cos(yn * 5.8 - 0.6) * 1.7
    h += math.sin(xn * 13.0 + 2.1) * math.cos(yn * 11.2 + 0.9) * 1.3
    h += math.sin(xn * 24.0 - 1.0) * math.sin(yn * 21.4 + 0.4) * 0.55
    for cx, cy, sigma, amp in valleys:
        h -= amp * gaussian_2d(x, y, cx, cy, sigma)
    for cx, cy, sigma, amp in hills:
        h += amp * gaussian_2d(x, y, cx, cy, sigma)
    return h


def height_at_raw(
    x: float,
    y: float,
    terrain_size: float,
    scene_layout: dict[str, Any],
    valleys: list[list[float]],
    hills: list[list[float]],
    roads: list[dict[str, Any]],
) -> float:
    h = base_height(x, y, terrain_size, valleys, hills)
    for key in ("plant_a", "plant_b", "building", "start_hub"):
        spec = scene_layout[key]
        cx, cy = spec["center"]
        hx, hy = spec["pad_half_extents"]
        nx = (x - cx) / max(1e-5, hx)
        ny = (y - cy) / max(1e-5, hy)
        inner = smoothstep(1.15, 0.80, math.sqrt(nx * nx + ny * ny))
        if inner > 0.0:
            h = h * (1.0 - inner) + spec["floor_z"] * inner
        sh = spec.get("surround_half_extents")
        if sh:
            snx = (x - cx) / max(1e-5, sh[0])
            sny = (y - cy) / max(1e-5, sh[1])
            surround = smoothstep(1.28, 0.82, math.sqrt(snx * snx + sny * sny))
            if surround > 0.0:
                h = h * (1.0 - surround * 0.82) + spec["floor_z"] * (surround * 0.82)

    best_dist = 1e9
    best_target = h
    for road in roads:
        p0, p1 = road["centerline"]
        dist, t = dist_point_to_segment(x, y, p0[0], p0[1], p1[0], p1[1])
        if dist < best_dist:
            best_dist = dist
            best_target = p0[2] + (p1[2] - p0[2]) * t
    road_cfg = scene_layout["roads"]
    blend = smoothstep(road_cfg["feather"], road_cfg["width"], best_dist)
    if blend > 0.0:
        h = h * (1.0 - blend * 0.92) + best_target * (blend * 0.92)
    return h


def add_box(
    objects: list[dict[str, Any]],
    object_id: str,
    kind: str,
    position: list[float],
    half_extents: list[float],
    color: list[float],
    *,
    rotation: list[float] | None = None,
    collision: bool = False,
    metadata: dict[str, Any] | None = None,
) -> None:
    size = [round(v * 2.0, 6) for v in half_extents]
    obj: dict[str, Any] = {
        "id": object_id,
        "kind": kind,
        "pose": {"position": [round(v, 6) for v in position], "rotation_euler_deg": [round(v, 6) for v in (rotation or [0.0, 0.0, 0.0])]},
        "geometry": {"type": "box", "half_extents": [round(v, 6) for v in half_extents], "size": size},
        "material": {"base_color": color},
        "metadata": metadata or {},
    }
    if collision:
        obj["collision"] = {"type": "box", "half_extents": [round(v, 6) for v in half_extents], "size": size}
        obj["metadata"]["obstacle"] = True
    objects.append(obj)


def build_heightfield(
    terrain_size: float,
    tile_count: int,
    scene_layout: dict[str, Any],
    valleys: list[list[float]],
    hills: list[list[float]],
    roads: list[dict[str, Any]],
) -> list[list[float]]:
    heights: list[list[float]] = []
    for row in range(tile_count):
        y = (row / (tile_count - 1)) * terrain_size - terrain_size / 2.0
        values = []
        for col in range(tile_count):
            x = (col / (tile_count - 1)) * terrain_size - terrain_size / 2.0
            values.append(round(height_at_raw(x, y, terrain_size, scene_layout, valleys, hills, roads), 5))
        heights.append(values)
    return heights


def build_scene(config: dict[str, Any]) -> dict[str, Any]:
    terrain_size = float(config["terrain_size"])
    tile_count = int(config["tile_count"])
    scene_layout = config["scene_layout"]
    roads = road_segments(scene_layout)
    heights = build_heightfield(terrain_size, tile_count, scene_layout, config["valleys"], config["hills"], roads)

    def terrain_height(x: float, y: float) -> float:
        cell = terrain_size / (tile_count - 1)
        off = terrain_size / 2.0
        col_f = (x + off) / cell
        row_f = (y + off) / cell
        col0 = max(0, min(tile_count - 2, int(col_f)))
        row0 = max(0, min(tile_count - 2, int(row_f)))
        tc = col_f - col0
        tr = row_f - row0
        h00 = heights[row0][col0]
        h01 = heights[row0][col0 + 1]
        h10 = heights[row0 + 1][col0]
        h11 = heights[row0 + 1][col0 + 1]
        return h00 * (1 - tc) * (1 - tr) + h01 * tc * (1 - tr) + h10 * (1 - tc) * tr + h11 * tc * tr

    objects: list[dict[str, Any]] = []
    keepouts: list[tuple[float, float, float]] = []

    def register_keepout(x: float, y: float, radius: float) -> None:
        keepouts.append((x, y, radius))

    def is_clear(x: float, y: float, radius: float) -> bool:
        for ox, oy, rr in keepouts:
            dx = x - ox
            dy = y - oy
            min_dist = radius + rr
            if dx * dx + dy * dy < min_dist * min_dist:
                return False
        return True

    road_keepout = scene_layout["roads"]["width"] + 1.5
    step = max(4.0, road_keepout * 0.85)
    for road in roads:
        p0, p1 = road["centerline"]
        dx = p1[0] - p0[0]
        dy = p1[1] - p0[1]
        seg_len = math.sqrt(dx * dx + dy * dy)
        samples = max(2, int(seg_len / step))
        for i in range(samples + 1):
            t = i / samples
            register_keepout(p0[0] + dx * t, p0[1] + dy * t, road_keepout)

    for key in ("plant_a", "plant_b", "building", "start_hub"):
        spec = scene_layout[key]
        hx, hy = spec["pad_half_extents"]
        register_keepout(spec["center"][0], spec["center"][1], math.sqrt(hx * hx + hy * hy) + 3.0)

    for idx, key in enumerate(("plant_a", "plant_b")):
        spec = scene_layout[key]
        cx, cy = spec["center"]
        hx, hy = spec["pad_half_extents"]
        floor_z = spec["floor_z"]
        add_box(objects, f"{key}_pad", "pad", [cx, cy, floor_z + 0.18], [hx, hy, 0.18], [0.28, 0.29, 0.30], metadata={"label": f"{spec['label']} pad", "parent": key})
        rows = 8
        cols = 8
        sx = (hx * 1.70) / (cols - 1)
        sy = (hy * 1.60) / (rows - 1)
        heading = 20.0 if idx == 0 else -18.0
        for r in range(rows):
            for c in range(cols):
                px = cx - hx * 0.85 + c * sx
                py = cy - hy * 0.80 + r * sy
                pz = terrain_height(px, py) + 0.86
                add_box(objects, f"{key}_frame_{r}_{c}", "solar_frame", [px, py, pz], [1.35, 0.08, 0.34], [0.60, 0.62, 0.65], rotation=[heading, 0.0, 0.0], metadata={"parent": key, "row": r, "column": c})
                add_box(objects, f"{key}_panel_{r}_{c}", "solar_panel", [px, py, pz + 0.42], [1.35, 0.95, 0.035], [0.08, 0.14, 0.24], rotation=[heading, 22.0, 0.0], metadata={"parent": key, "row": r, "column": c})
        add_box(objects, f"{key}_collider", "collision_proxy", [cx, cy, floor_z + 1.2], [hx * 0.98, hy * 0.98, 1.2], [0.0, 0.0, 0.0], collision=True, metadata={"parent": key, "visible": False})

    bld = scene_layout["building"]
    cx, cy = bld["center"]
    floor_z = bld["floor_z"]
    hx, hy = bld["pad_half_extents"]
    add_box(objects, "building_pad", "pad", [cx, cy, floor_z + 0.24], [hx, hy, 0.24], [0.38, 0.37, 0.34], metadata={"label": "Operations Building pad", "parent": "building"})
    add_box(objects, "ops_building_base", "building", [cx, cy, floor_z + 2.8], [8.0, 5.5, 2.8], [0.74, 0.74, 0.70], metadata={"label": bld["label"], "parent": "building"})
    add_box(objects, "ops_building_roof", "building", [cx, cy, floor_z + 5.9], [8.5, 6.0, 0.26], [0.22, 0.23, 0.24], metadata={"parent": "building"})
    add_box(objects, "ops_building_collider", "collision_proxy", [cx, cy, floor_z + 2.9], [8.2, 5.8, 2.9], [0.0, 0.0, 0.0], collision=True, metadata={"parent": "building", "visible": False})

    hub = scene_layout["start_hub"]
    cx, cy = hub["center"]
    floor_z = hub["floor_z"]
    hx, hy = hub["pad_half_extents"]
    add_box(objects, "start_hub_pad", "pad", [cx, cy, floor_z + 0.22], [hx, hy, 0.22], [0.52, 0.53, 0.54], metadata={"label": hub["label"], "parent": "start_hub"})
    add_box(objects, "start_hub_pad_collider", "collision_proxy", [cx, cy, floor_z + 0.22], [hx, hy, 0.22], [0.0, 0.0, 0.0], collision=True, metadata={"parent": "start_hub", "visible": False})
    add_box(objects, "charger_base", "charger", [cx + 8.4, cy - 5.4, floor_z + 0.30], [1.15, 0.72, 0.30], [0.28, 0.30, 0.33], metadata={"parent": "start_hub"})
    add_box(objects, "charger_post", "charger", [cx + 8.4, cy - 5.4, floor_z + 1.45], [0.22, 0.22, 1.15], [0.70, 0.72, 0.74], metadata={"parent": "start_hub"})
    add_box(objects, "charger_head", "charger", [cx + 8.4, cy - 5.2, floor_z + 2.38], [0.36, 0.20, 0.18], [0.19, 0.52, 0.36], metadata={"parent": "start_hub"})
    add_box(objects, "hub_guard_rail", "guard_rail", [cx + hx - 0.8, cy, floor_z + 0.42], [0.12, 4.1, 0.42], [0.78, 0.79, 0.80], metadata={"parent": "start_hub"})
    add_box(objects, "charger_collider", "collision_proxy", [cx + 8.4, cy - 5.4, floor_z + 0.95], [0.85, 0.55, 0.95], [0.0, 0.0, 0.0], collision=True, metadata={"parent": "start_hub", "visible": False})

    spawn_xy = scene_layout["spawn"]["xy"]
    spawn_z = terrain_height(spawn_xy[0], spawn_xy[1]) + 2.2

    rng = random.Random(42)
    placed = 0
    attempts = 0
    small_stones = 42
    total_stones = 60
    while placed < total_stones and attempts < 2600:
        attempts += 1
        px = rng.uniform(-terrain_size * 0.46, terrain_size * 0.46)
        py = rng.uniform(-terrain_size * 0.46, terrain_size * 0.46)
        if math.hypot(px - spawn_xy[0], py - spawn_xy[1]) < 18.0:
            continue
        is_big = placed >= small_stones
        if is_big:
            radius = rng.uniform(1.15, 2.20)
            rx = radius * rng.uniform(0.95, 1.55)
            ry = radius * rng.uniform(0.95, 1.55)
            rz = radius * rng.uniform(0.70, 1.20)
        else:
            radius = rng.uniform(0.45, 1.20)
            rx = radius * rng.uniform(0.80, 1.45)
            ry = radius * rng.uniform(0.80, 1.45)
            rz = radius * rng.uniform(0.60, 1.05)
        footprint = max(radius, rx, ry) * (1.18 if is_big else 1.05)
        if not is_clear(px, py, footprint):
            continue
        stone_z = terrain_height(px, py) + rz * (0.55 if is_big else 0.60)
        tag = "boulder" if is_big else "stone"
        color = [0.39, 0.36, 0.33] if is_big else [0.44, 0.40, 0.35]
        objects.append({
            "id": f"{tag}_{placed}",
            "kind": tag,
            "pose": {
                "position": [round(px, 6), round(py, 6), round(stone_z, 6)],
                "rotation_euler_deg": [round(rng.uniform(0, 360), 6), round(rng.uniform(-15, 15), 6), round(rng.uniform(-15, 15), 6)],
            },
            "geometry": {"type": "ellipsoid", "radii": [round(rx, 6), round(ry, 6), round(rz, 6)], "seed": placed},
            "collision": {"type": "sphere", "radius": round(radius, 6)},
            "material": {"base_color": color, "jitter": 0.09 if is_big else 0.07},
            "metadata": {"obstacle": True, "footprint_radius": round(footprint, 6), "route_planning_cost": "blocked"},
        })
        register_keepout(px, py, footprint)
        placed += 1

    rng = random.Random(314)
    placed = 0
    attempts = 0
    while placed < 28 and attempts < 2400:
        attempts += 1
        px = rng.uniform(-terrain_size * 0.47, terrain_size * 0.47)
        py = rng.uniform(-terrain_size * 0.47, terrain_size * 0.47)
        if math.hypot(px - spawn_xy[0], py - spawn_xy[1]) < 20.0:
            continue
        trunk_r = rng.uniform(0.24, 0.40)
        trunk_h = rng.uniform(1.9, 3.4)
        canopy_r = rng.uniform(1.25, 2.65)
        footprint = max(trunk_r * 1.6, canopy_r * 0.55)
        if not is_clear(px, py, footprint):
            continue
        hpr = [rng.uniform(0, 360), rng.uniform(-3, 3), rng.uniform(-3, 3)]
        trunk_rx = trunk_r * rng.uniform(0.85, 1.18)
        trunk_ry = trunk_r * rng.uniform(0.85, 1.18)
        trunk_rz = trunk_h * 0.5
        canopy_rx = canopy_r * rng.uniform(0.80, 1.18)
        canopy_ry = canopy_r * rng.uniform(0.80, 1.18)
        canopy_rz = canopy_r * rng.uniform(0.72, 1.08)
        objects.append({
            "id": f"tree_{placed}",
            "kind": "tree",
            "pose": {
                "position": [round(px, 6), round(py, 6), round(terrain_height(px, py), 6)],
                "rotation_euler_deg": [round(v, 6) for v in hpr],
            },
            "geometry": {
                "type": "compound",
                "parts": [
                    {"id": "trunk", "type": "ellipsoid", "radii": [round(trunk_rx, 6), round(trunk_ry, 6), round(trunk_rz, 6)], "local_position": [0.0, 0.0, round(trunk_rz * 0.95, 6)], "seed": 5000 + placed, "material": {"base_color": [0.32, 0.23, 0.13], "jitter": 0.04}},
                    {"id": "canopy", "type": "ellipsoid", "radii": [round(canopy_rx, 6), round(canopy_ry, 6), round(canopy_rz, 6)], "local_position": [0.0, 0.0, round(trunk_h + canopy_rz * 0.22, 6)], "seed": 7000 + placed, "material": {"base_color": [0.19, 0.45, 0.17], "jitter": 0.06}},
                ],
            },
            "collision": {"type": "cylinder", "radius": round(footprint, 6), "height": round(trunk_h + canopy_rz, 6)},
            "metadata": {"obstacle": True, "footprint_radius": round(footprint, 6), "route_planning_cost": "blocked"},
        })
        register_keepout(px, py, footprint)
        placed += 1

    half = terrain_size / 2.0
    flat = [h for row in heights for h in row]
    return {
        "schema_version": "terrain-scene/v1",
        "generator": {"name": "tools/generate_terrain_scene.py", "legacy_source": "config/terrain_scene.json"},
        "units": {"linear": "m", "angular": "deg"},
        "coordinate_system": {
            "up_axis": "Z",
            "x_axis": "east",
            "y_axis": "north",
            "origin": [0.0, 0.0, 0.0],
            "georeference": {
                "type": "local_tangent_plane",
                "origin_lat": 40.170000,
                "origin_lon": 44.500000,
                "origin_alt": 0.0,
                "origin_local": [0.0, 0.0, 0.0],
                "notes": "Artificial GPS anchor for the virtual 3D terrain. X is east meters, Y is north meters, Z is altitude meters.",
            },
        },
        "bounds": {"min": [-half, -half, round(min(flat), 5)], "max": [half, half, round(max(flat), 5)]},
        "terrain": {
            "id": "terrain",
            "kind": "heightfield",
            "size": [terrain_size, terrain_size],
            "tile_count": tile_count,
            "heightfield": heights,
        },
        "roads": roads,
        "objects": objects,
        "spawn_points": [{"id": "default_spawn", "pose": {"position": [round(spawn_xy[0], 6), round(spawn_xy[1], 6), round(spawn_z, 6)], "rotation_euler_deg": [0.0, 0.0, 0.0]}}],
    }


def main() -> None:
    with LEGACY_CONFIG.open("r", encoding="utf-8") as fh:
        config = json.load(fh)
    scene = build_scene(config)
    with OUTPUT.open("w", encoding="utf-8") as fh:
        json.dump(scene, fh, indent=2)
        fh.write("\n")
    print(f"Wrote {OUTPUT.relative_to(ROOT)} with {len(scene['objects'])} objects and {len(scene['roads'])} roads.")


if __name__ == "__main__":
    main()
