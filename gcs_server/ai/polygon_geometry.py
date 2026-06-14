"""Planar polygon geometry primitives shared by the operational-constraints
store (geometry validation) and the mission planner (hard route-segment checks).

Points are ``(x, y)`` tuples. Callers pass WGS84 as ``(lon, lat)`` and treat the
small operating area as planar — the same flat approximation the legacy
ray-casting point-in-polygon used. Rings are *open* (first vertex not repeated);
every function closes the ring implicitly by joining the last vertex to the first.
"""

from __future__ import annotations

import math

Point = tuple[float, float]

# Areas/lengths are in squared/linear degrees. ~1e-9 deg ≈ 0.1 mm at the equator,
# small enough to treat as numerically zero without rejecting real polygons.
_AREA_EPS = 1e-12


def _orient(o: Point, a: Point, b: Point) -> float:
    """Twice the signed area of triangle (o, a, b). >0 left turn, <0 right, 0 collinear."""
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _on_segment(a: Point, b: Point, p: Point) -> bool:
    """True when collinear point ``p`` lies within segment ``a``–``b``'s bounding box."""
    return (
        min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
        and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
    )


def segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    """True if segment ``a``–``b`` intersects segment ``c``–``d`` (including touching
    and collinear overlap)."""
    d1 = _orient(c, d, a)
    d2 = _orient(c, d, b)
    d3 = _orient(a, b, c)
    d4 = _orient(a, b, d)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return True
    if d1 == 0 and _on_segment(c, d, a):
        return True
    if d2 == 0 and _on_segment(c, d, b):
        return True
    if d3 == 0 and _on_segment(a, b, c):
        return True
    if d4 == 0 and _on_segment(a, b, d):
        return True
    return False


def signed_area(ring: list[Point]) -> float:
    """Shoelace signed area of the open ring (positive CCW, negative CW)."""
    n = len(ring)
    total = 0.0
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def is_degenerate(ring: list[Point]) -> bool:
    """True if the ring has fewer than 3 vertices or ~zero area (all collinear)."""
    return len(ring) < 3 or abs(signed_area(ring)) <= _AREA_EPS


def self_intersects(ring: list[Point]) -> bool:
    """True if any two non-adjacent edges of the ring cross or touch. Adjacent
    edges legitimately share a vertex and are skipped."""
    n = len(ring)
    edges = [(ring[i], ring[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        a1, a2 = edges[i]
        for j in range(i + 1, n):
            # Skip edges that share a vertex (adjacent, or the closing/first wrap).
            if j == i or (i + 1) % n == j or (j + 1) % n == i:
                continue
            b1, b2 = edges[j]
            if segments_intersect(a1, a2, b1, b2):
                return True
    return False


def point_in_ring(p: Point, ring: list[Point]) -> bool:
    """Ray-casting point-in-polygon. Boundary membership is not guaranteed (a point
    exactly on an edge may read either way) — callers needing boundary-inclusive
    behaviour should sub-sample interiors, which the segment routines below do."""
    x, y = p
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _segment_edge_crossing_ts(a: Point, b: Point, ring: list[Point]) -> list[float]:
    """Parameters ``t`` in (0, 1) where segment ``a``+t*(b-a) crosses a ring edge."""
    ts: list[float] = []
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    n = len(ring)
    for i in range(n):
        c = ring[i]
        d = ring[(i + 1) % n]
        denom = dx * (d[1] - c[1]) - dy * (d[0] - c[0])
        if denom == 0:
            continue  # parallel (collinear overlap handled by interior sampling)
        t = ((c[0] - ax) * (d[1] - c[1]) - (c[1] - ay) * (d[0] - c[0])) / denom
        s = ((c[0] - ax) * dy - (c[1] - ay) * dx) / denom
        if 0.0 < t < 1.0 and 0.0 <= s <= 1.0:
            ts.append(t)
    return ts


def _subinterval_midpoints(a: Point, b: Point, ring: list[Point]) -> list[Point]:
    """Midpoints of every sub-segment of ``a``–``b`` partitioned by its crossings
    with ``ring``. Each midpoint lies strictly inside or strictly outside ``ring``,
    so ``point_in_ring`` classifies the whole sub-segment unambiguously."""
    ts = sorted({0.0, 1.0, *_segment_edge_crossing_ts(a, b, ring)})
    ax, ay = a
    bx, by = b
    mids: list[Point] = []
    for t0, t1 in zip(ts, ts[1:]):
        tm = (t0 + t1) / 2.0
        mids.append((ax + (bx - ax) * tm, ay + (by - ay) * tm))
    return mids


def segment_enters_polygon(a: Point, b: Point, ring: list[Point]) -> bool:
    """True if any portion of segment ``a``–``b`` lies inside ``ring`` (a blockage).
    Catches the case where both endpoints are outside but the segment cuts through."""
    return any(point_in_ring(m, ring) for m in _subinterval_midpoints(a, b, ring))


def segment_within_union(a: Point, b: Point, rings: list[list[Point]]) -> bool:
    """True if every portion of segment ``a``–``b`` lies inside the union of
    ``rings`` (the hard allowed-corridor union). The segment is partitioned by its
    crossings with *all* rings, then each sub-segment midpoint must fall inside at
    least one ring."""
    ts = {0.0, 1.0}
    for ring in rings:
        ts.update(_segment_edge_crossing_ts(a, b, ring))
    ordered = sorted(ts)
    ax, ay = a
    bx, by = b
    for t0, t1 in zip(ordered, ordered[1:]):
        tm = (t0 + t1) / 2.0
        mid = (ax + (bx - ax) * tm, ay + (by - ay) * tm)
        if not any(point_in_ring(mid, ring) for ring in rings):
            return False
    return True


def _segment_length(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def segment_length_inside_ring(a: Point, b: Point, ring: list[Point]) -> float:
    """Length of the portion of segment ``a``–``b`` that lies inside ``ring``."""
    ts = sorted({0.0, 1.0, *_segment_edge_crossing_ts(a, b, ring)})
    ax, ay = a
    bx, by = b
    total = 0.0
    for t0, t1 in zip(ts, ts[1:]):
        tm = (t0 + t1) / 2.0
        mid = (ax + (bx - ax) * tm, ay + (by - ay) * tm)
        if point_in_ring(mid, ring):
            start = (ax + (bx - ax) * t0, ay + (by - ay) * t0)
            end = (ax + (bx - ax) * t1, ay + (by - ay) * t1)
            total += _segment_length(start, end)
    return total


def segment_length_outside_union(a: Point, b: Point, rings: list[list[Point]]) -> float:
    """Length of the portion of segment ``a``–``b`` outside the union of ``rings``."""
    if not rings:
        return _segment_length(a, b)
    ts = {0.0, 1.0}
    for ring in rings:
        ts.update(_segment_edge_crossing_ts(a, b, ring))
    ordered = sorted(ts)
    ax, ay = a
    bx, by = b
    total = 0.0
    for t0, t1 in zip(ordered, ordered[1:]):
        tm = (t0 + t1) / 2.0
        mid = (ax + (bx - ax) * tm, ay + (by - ay) * tm)
        if not any(point_in_ring(mid, ring) for ring in rings):
            start = (ax + (bx - ax) * t0, ay + (by - ay) * t0)
            end = (ax + (bx - ax) * t1, ay + (by - ay) * t1)
            total += _segment_length(start, end)
    return total
