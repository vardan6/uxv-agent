"""Pure, relocatable mission safety geometry (ADR 0023 Phase 5).

Defense-in-depth geofencing has two layers: the flight controller is
*authoritative* (it enforces the uploaded FENCE/RALLY at the firmware level),
and the executor validates *early* — before it drives a single nav segment —
so a mission that would breach the fence fails closed instead of being handed to
the FC and rejected mid-run.

This module is the self-contained core both layers share: a WGS84 inclusion
fence + rally points, JSON round-trip, and a fail-closed waypoint validator. It
imports nothing from GCS internals so the executor stays relocatable (a
companion-computer build reuses it unchanged). It deliberately works in WGS84
(the stored truth per ADR 0022) and does no projection — point-in-polygon on
lat/lon is accurate enough for the inclusion test at rover scale, and keeping it
projection-free avoids dragging the coordinate-frame seam into the executor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# Mirror the MAVLink MAV_MISSION_TYPE values so the FC-upload layer can key off
# the same constants without re-deriving them.
MISSION_TYPE_FENCE = 1
MISSION_TYPE_RALLY = 2


@dataclass(frozen=True)
class FencePoint:
    """One vertex of an inclusion polygon, in WGS84."""

    lat: float
    lon: float

    def to_dict(self) -> dict[str, float]:
        return {"lat": float(self.lat), "lon": float(self.lon)}


@dataclass(frozen=True)
class RallyPoint:
    """A safe-return point the FC may divert to. WGS84 + altitude (m)."""

    lat: float
    lon: float
    alt: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {"lat": float(self.lat), "lon": float(self.lon), "alt": float(self.alt)}


@dataclass
class Geofence:
    """An inclusion fence: waypoints must lie inside ``polygon`` and (when a band
    is set) within ``[min_alt, max_alt]``. Rally points ride along for FC upload.

    A polygon with fewer than three vertices is *not* a usable fence; validation
    treats it as fail-closed (every waypoint is a violation) rather than silently
    passing, so a malformed fence can never weaken the check.
    """

    polygon: list[FencePoint] = field(default_factory=list)
    rally_points: list[RallyPoint] = field(default_factory=list)
    min_alt: Optional[float] = None
    max_alt: Optional[float] = None

    @property
    def is_usable(self) -> bool:
        return len(self.polygon) >= 3

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "polygon": [p.to_dict() for p in self.polygon],
            "rally_points": [r.to_dict() for r in self.rally_points],
        }
        if self.min_alt is not None:
            out["min_alt"] = float(self.min_alt)
        if self.max_alt is not None:
            out["max_alt"] = float(self.max_alt)
        return out


@dataclass(frozen=True)
class FenceViolation:
    """A single waypoint that breaches the fence, for fail-closed reporting."""

    index: int
    reason: str  # "outside_polygon" | "below_min_alt" | "above_max_alt" | "no_fence"
    lat: float
    lon: float
    alt: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": int(self.index),
            "reason": self.reason,
            "lat": float(self.lat),
            "lon": float(self.lon),
            "alt": float(self.alt),
        }


def _coerce_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_geofence(data: Any) -> Geofence:
    """Parse a fence dict (the ``to_dict`` shape) into a :class:`Geofence`.

    Unknown / malformed entries are dropped; the result may be non-usable, in
    which case validation fails closed. Round-trips ``Geofence.to_dict``.
    """
    if not isinstance(data, dict):
        return Geofence()
    polygon: list[FencePoint] = []
    for raw in data.get("polygon") or []:
        if not isinstance(raw, dict):
            continue
        lat, lon = _coerce_float(raw.get("lat")), _coerce_float(raw.get("lon"))
        if lat is None or lon is None:
            continue
        polygon.append(FencePoint(lat=lat, lon=lon))
    rally: list[RallyPoint] = []
    for raw in data.get("rally_points") or []:
        if not isinstance(raw, dict):
            continue
        lat, lon = _coerce_float(raw.get("lat")), _coerce_float(raw.get("lon"))
        if lat is None or lon is None:
            continue
        rally.append(RallyPoint(lat=lat, lon=lon, alt=_coerce_float(raw.get("alt")) or 0.0))
    return Geofence(
        polygon=polygon,
        rally_points=rally,
        min_alt=_coerce_float(data.get("min_alt")),
        max_alt=_coerce_float(data.get("max_alt")),
    )


def _point_in_polygon(lat: float, lon: float, polygon: list[FencePoint]) -> bool:
    """Ray-casting point-in-polygon on (lon=x, lat=y). A point on an edge counts
    as inside (fail-open only at the exact boundary, which the FC then owns)."""
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i].lon, polygon[i].lat
        xj, yj = polygon[j].lon, polygon[j].lat
        # Does the horizontal ray at `lat` cross edge (j -> i)?
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def validate_waypoints(
    waypoints: list[dict[str, Any]],
    fence: Optional[Geofence],
) -> list[FenceViolation]:
    """Return every waypoint that breaches ``fence`` (empty list == all clear).

    Fail-closed: a missing or non-usable fence makes *every* waypoint a
    ``no_fence`` violation, so the executor refuses to drive rather than running
    unfenced. Waypoints are read as WGS84 (``lat``/``lon``/``alt``), matching the
    stored truth; an out-of-band altitude is reported alongside polygon breaches.
    """
    violations: list[FenceViolation] = []
    usable = fence is not None and fence.is_usable
    for index, wp in enumerate(waypoints or []):
        lat = _coerce_float(wp.get("lat")) or 0.0
        lon = _coerce_float(wp.get("lon")) or 0.0
        alt = _coerce_float(wp.get("alt")) or 0.0
        if not usable:
            violations.append(FenceViolation(index, "no_fence", lat, lon, alt))
            continue
        assert fence is not None  # narrowed by `usable`
        if not _point_in_polygon(lat, lon, fence.polygon):
            violations.append(FenceViolation(index, "outside_polygon", lat, lon, alt))
            continue
        if fence.min_alt is not None and alt < fence.min_alt:
            violations.append(FenceViolation(index, "below_min_alt", lat, lon, alt))
        elif fence.max_alt is not None and alt > fence.max_alt:
            violations.append(FenceViolation(index, "above_max_alt", lat, lon, alt))
    return violations
