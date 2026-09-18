from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VehicleProfile:
    id: str
    kind: Literal["ground", "multirotor", "fixed_wing"]
    mav_vehicle_type: int  # 10=rover, 2=multirotor, 1=fixed-wing
    planner_kind: Literal["road_graph", "aerial_survey", "airspace_corridor"]
    default_cruise_alt_m: float  # 0 for ground vehicles
    supports_yaw_at_waypoint: bool
    max_speed_mps: float


ROVER_DEFAULT = VehicleProfile(
    id="rover_default",
    kind="ground",
    mav_vehicle_type=10,
    planner_kind="road_graph",
    default_cruise_alt_m=0.0,
    supports_yaw_at_waypoint=False,
    max_speed_mps=2.0,
)

QUAD_X500 = VehicleProfile(
    id="quad_x500",
    kind="multirotor",
    mav_vehicle_type=2,
    planner_kind="aerial_survey",
    default_cruise_alt_m=30.0,
    supports_yaw_at_waypoint=True,
    max_speed_mps=10.0,
)

FIXED_WING_DEFAULT = VehicleProfile(
    id="fixed_wing_default",
    kind="fixed_wing",
    mav_vehicle_type=1,
    planner_kind="airspace_corridor",
    default_cruise_alt_m=100.0,
    supports_yaw_at_waypoint=False,
    max_speed_mps=25.0,
)

KNOWN_PROFILES: dict[str, VehicleProfile] = {
    p.id: p for p in [ROVER_DEFAULT, QUAD_X500, FIXED_WING_DEFAULT]
}


DEFAULT_PROFILE_ID = ROVER_DEFAULT.id

# Settings key holding the operator's persisted selection.
SETTINGS_SECTION = "vehicle_profile"
SETTINGS_KEY = "active_profile_id"


def resolve_active_profile(config: Any) -> VehicleProfile:
    """Read the persisted selection, falling back to the default profile.

    The read path is deliberately tolerant: a settings file naming a profile
    this build does not ship must not break planning or export. The write path
    (`POST /api/vehicle-profile/active`) rejects unknown IDs instead.
    """
    section = getattr(config, SETTINGS_SECTION, None)
    if not isinstance(section, dict):
        section = {}
    profile_id = section.get(SETTINGS_KEY)
    if profile_id is None:
        return ROVER_DEFAULT
    profile = KNOWN_PROFILES.get(str(profile_id))
    if profile is None:
        logger.warning(
            "unknown %s.%s %r in settings; falling back to %s",
            SETTINGS_SECTION,
            SETTINGS_KEY,
            profile_id,
            DEFAULT_PROFILE_ID,
        )
        return ROVER_DEFAULT
    return profile


def get_active_profile(config: Any | None = None) -> VehicleProfile:
    # Callers that hold a config resolve the operator's selection; the
    # remaining zero-argument call sites still get rover_default until R3
    # slice 2 threads the config through them.
    if config is None:
        return ROVER_DEFAULT
    return resolve_active_profile(config)
