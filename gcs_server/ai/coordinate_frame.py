"""Coordinate-frame primitives for the GPS-master mission model (ADR 0022).

WGS84 lat/lon/alt is the stored, authoritative coordinate for a waypoint; local
scene metres ``{x, y, z}`` is a *derived, displayed* view. Each Mission carries
its own ``Origin`` (datum); that origin is the single link used to convert
between the two frames in either direction.

Conversion is flat-earth (equirectangular about the origin latitude). It stays
sub-metre-accurate over a rover's working area; large-area / multi-site accuracy
is an Open Question in ADR 0022.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

# 1 degree of latitude ≈ 111_320 m; 1 degree of longitude ≈ that × cos(lat).
_METRES_PER_DEG_LAT = 111_320.0

_SCENE_PATH = Path(__file__).resolve().parents[2] / "config" / "terrain_scene.v1.json"


@dataclass(frozen=True)
class Origin:
    """A Mission's datum: the WGS84 point that local metres are measured from.

    In the simulator this is seeded from the terrain scene's georeference; on a
    real rover it comes from the rover's GPS / home position.
    """

    lat: float
    lon: float
    alt: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {"origin_lat": self.lat, "origin_lon": self.lon, "origin_alt": self.alt}

    @classmethod
    def from_dict(cls, data: dict[str, float]) -> "Origin":
        return cls(
            lat=float(data.get("origin_lat", 0.0)),
            lon=float(data.get("origin_lon", 0.0)),
            alt=float(data.get("origin_alt", 0.0)),
        )


def local_to_wgs84(x: float, y: float, z: float, origin: Origin) -> tuple[float, float, float]:
    """Flat-earth projection from local metres (ENU: x=east, y=north, z=up) to WGS84."""
    lat = origin.lat + y / _METRES_PER_DEG_LAT
    lon = origin.lon + x / (_METRES_PER_DEG_LAT * math.cos(math.radians(origin.lat)))
    alt = origin.alt + z
    return lat, lon, alt


def wgs84_to_local(lat: float, lon: float, alt: float, origin: Origin) -> tuple[float, float, float]:
    """Inverse of :func:`local_to_wgs84`: WGS84 to local metres (ENU)."""
    y = (lat - origin.lat) * _METRES_PER_DEG_LAT
    x = (lon - origin.lon) * (_METRES_PER_DEG_LAT * math.cos(math.radians(origin.lat)))
    z = alt - origin.alt
    return x, y, z


def load_scene_origin(scene_path: str | Path | None = None) -> Origin:
    """Seed an Origin from the simulator terrain scene's georeference."""
    path = Path(scene_path) if scene_path else _SCENE_PATH
    scene = json.loads(path.read_text())
    geo = scene.get("coordinate_system", {}).get("georeference", {})
    return Origin.from_dict(geo)
