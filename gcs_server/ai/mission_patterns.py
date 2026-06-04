"""Navigation-pattern generators (ADR 0023, Phase 4 — Authoring UX).

Authoring a mission by hand waypoint-by-waypoint is tedious for the two shapes
operators reach for most: a *corridor* (drive a path, optionally back and forth)
and a *survey* (cover an area in a lawnmower sweep). This module turns a handful
of geometric parameters into a navigation subtree — a ``nav_leaf`` (or a
``sequence`` of them) of :class:`~ai.mission_tree.Node` — that drops straight
into a Mission's behavior tree and compiles to ``.plan`` like any other nav run.

Coordinate frame: generators work entirely in the local scene metre frame
(ENU: ``x`` east, ``y`` north, ``z`` up), matching the route tools. WGS84 truth
is stamped on storage from the Mission origin (ADR 0022), so nothing here needs
the datum. The module imports only stdlib + :mod:`ai.mission_tree`, so it stays
relocatable with the rest of the tree model.
"""

from __future__ import annotations

import math
from typing import Any

from . import mission_tree


def _waypoint(x: float, y: float, z: float, **extra: Any) -> dict[str, Any]:
    """One local-metre waypoint dict, shaped like the route tools emit."""
    wp: dict[str, Any] = {"x": float(x), "y": float(y), "z": float(z)}
    wp.update(extra)
    return wp


def _densify_segment(
    x0: float, y0: float, x1: float, y1: float, spacing_m: float, z: float
) -> list[dict[str, Any]]:
    """Points along the segment (x0,y0)->(x1,y1) every ``spacing_m`` metres.

    Includes the start point and always the exact end point; intermediate points
    are evenly spaced so the real interval is ``length / ceil(length/spacing)``
    (<= spacing), avoiding a stub at the end.
    """
    length = math.hypot(x1 - x0, y1 - y0)
    points = [_waypoint(x0, y0, z)]
    if length == 0.0:
        return points
    steps = max(1, math.ceil(length / spacing_m))
    for i in range(1, steps + 1):
        t = i / steps
        points.append(_waypoint(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, z))
    return points


def corridor_pattern(
    path: list[tuple[float, float]],
    spacing_m: float,
    altitude_m: float,
    *,
    passes: int = 1,
    name: str = "corridor",
) -> mission_tree.Node:
    """A path-following navigation subtree.

    ``path`` is an ordered polyline of ``(x, y)`` local-metre vertices (>= 2).
    The polyline is densified so consecutive waypoints are at most ``spacing_m``
    apart; each waypoint sits at ``altitude_m``. ``passes`` >= 2 walks the
    corridor back and forth that many times (a return pass reverses direction),
    which is the common "sweep this lane repeatedly" ask.

    Returns a single ``nav_leaf`` when ``passes == 1``, else a ``sequence`` of
    one ``nav_leaf`` per pass so the executor (and overlays) can address them.
    """
    if len(path) < 2:
        raise ValueError("corridor_pattern requires a path of at least two points")
    if spacing_m <= 0:
        raise ValueError("corridor_pattern spacing_m must be > 0")
    if passes < 1:
        raise ValueError("corridor_pattern passes must be >= 1")

    def _one_pass(vertices: list[tuple[float, float]]) -> list[dict[str, Any]]:
        waypoints: list[dict[str, Any]] = []
        for i in range(len(vertices) - 1):
            (x0, y0), (x1, y1) = vertices[i], vertices[i + 1]
            seg = _densify_segment(x0, y0, x1, y1, spacing_m, altitude_m)
            # Drop the duplicated join point between consecutive segments.
            waypoints.extend(seg if i == 0 else seg[1:])
        return waypoints

    leaves: list[mission_tree.Node] = []
    for p in range(passes):
        vertices = list(path) if p % 2 == 0 else list(reversed(path))
        leaves.append(
            mission_tree.Node(
                type=mission_tree.NAV_LEAF,
                name=f"{name} pass {p + 1}" if passes > 1 else name,
                waypoints=_one_pass(vertices),
            )
        )

    if len(leaves) == 1:
        return leaves[0]
    return mission_tree.Node(type=mission_tree.SEQUENCE, name=name, children=leaves)


def survey_pattern(
    width_m: float,
    height_m: float,
    line_spacing_m: float,
    altitude_m: float,
    *,
    origin_xy: tuple[float, float] = (0.0, 0.0),
    heading_deg: float = 0.0,
    name: str = "survey",
) -> mission_tree.Node:
    """A lawnmower (boustrophedon) area-coverage navigation subtree.

    Covers a ``width_m`` x ``height_m`` rectangle whose lower-left corner is
    ``origin_xy`` with parallel survey lines ``line_spacing_m`` apart, sweeping
    back and forth so the path is continuous. Lines run along the local +x axis
    and step along +y; ``heading_deg`` rotates the whole pattern about
    ``origin_xy`` (0 = lines point east). All waypoints sit at ``altitude_m``.

    Returns a single ``nav_leaf`` — the sweep is one continuous navigable run.
    """
    if width_m <= 0 or height_m <= 0:
        raise ValueError("survey_pattern width_m and height_m must be > 0")
    if line_spacing_m <= 0:
        raise ValueError("survey_pattern line_spacing_m must be > 0")

    ox, oy = origin_xy
    theta = math.radians(heading_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)

    def _place(lx: float, ly: float) -> dict[str, Any]:
        # Rotate the local (lx, ly) offset by heading, then translate to origin.
        x = ox + lx * cos_t - ly * sin_t
        y = oy + lx * sin_t + ly * cos_t
        return _waypoint(x, y, altitude_m)

    # Survey lines step along +y; include the far edge so coverage reaches it.
    line_count = max(1, math.ceil(height_m / line_spacing_m)) + 1
    waypoints: list[dict[str, Any]] = []
    for i in range(line_count):
        ly = min(i * line_spacing_m, height_m)
        # Even lines run +x, odd lines run -x, so the path snakes continuously.
        if i % 2 == 0:
            waypoints.append(_place(0.0, ly))
            waypoints.append(_place(width_m, ly))
        else:
            waypoints.append(_place(width_m, ly))
            waypoints.append(_place(0.0, ly))

    return mission_tree.Node(
        type=mission_tree.NAV_LEAF, name=name, waypoints=waypoints
    )
