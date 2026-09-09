"""Bridge the behavior-tree executor's ``leaf_driver`` seam to the controller
adapter (ADR 0023 decision 3, Phase 3).

The executor (:mod:`ai.mission_executor`) is relocatable and never imports GCS
internals; it calls an injected ``leaf_driver(waypoints) -> bool`` for each
``nav_leaf``. In the server phase that seam is satisfied here: a navigable
segment of WGS84 waypoints is compiled to a QGC ``.plan`` via
:class:`MissionExportService` and installed on the flight controller through a
:class:`ControllerMissionAdapter`. Returns ``True`` only when the adapter
reports a verified install.

Keeping this glue in its own module — not in the executor — preserves the
executor's relocatability: a companion-computer build supplies a different
``leaf_driver`` that drives the FC directly.
"""

from __future__ import annotations

from typing import Any, Optional

from backend.ai.controller_mission_adapter import ControllerMissionAdapter
from backend.ai.mission_executor import LeafDriver
from backend.ai.mission_export_service import MissionExportService
from backend.ai.vehicle_profile import VehicleProfile


def make_controller_leaf_driver(
    adapter: ControllerMissionAdapter,
    *,
    export_service: Optional[MissionExportService] = None,
    profile: Optional[VehicleProfile] = None,
    home_position: Optional[dict[str, float]] = None,
    geofence: Optional[dict[str, Any]] = None,
    expected_controller_version: Optional[int] = None,
) -> LeafDriver:
    """Build a ``leaf_driver`` that installs each segment on the controller.

    ``export_service`` defaults to a fresh :class:`MissionExportService`;
    ``profile`` defaults to the active vehicle profile (resolved per call so a
    profile change takes effect without rebuilding the driver).

    Controller-version safety (ADR 0020 / ADR 0021): the executor is the sole
    writer for the duration of a run, so per-segment installs after the first do
    not re-assert a version. But the *first* install is gated against
    ``expected_controller_version`` (the version observed when the run was
    authorized) so a third party that mutated the controller between authorization
    and start causes the first install to fail the CAS rather than silently
    overwriting their state. ``None`` skips the gate (legacy behavior).

    When ``geofence`` (a :func:`ai.mission_safety.parse_geofence` ``to_dict``
    shape) is supplied, the inclusion FENCE/RALLY is uploaded to the controller
    once — lazily, before the first segment is driven — so the FC's
    authoritative layer is armed before any nav waypoint is installed (ADR 0023
    Phase 5). A failed fence upload fails closed: the segment is refused.
    """
    service = export_service or MissionExportService()
    # One-shot fence upload guarded across the per-segment calls of a run.
    fence_state = {"uploaded": False}
    # The version gate applies only to the first segment install of a run.
    install_state = {"first": True}

    def _ensure_geofence() -> bool:
        if not geofence or fence_state["uploaded"]:
            return True
        result = adapter.upload_geofence(geofence=geofence)
        if not result.ok:
            return False
        fence_state["uploaded"] = True
        return True

    def _drive(waypoints: list[dict[str, Any]]) -> bool:
        if not waypoints:
            # An empty segment is a no-op success: nothing to upload, and the
            # tree walk already accounted for the (zero) waypoints.
            return True
        if not _ensure_geofence():
            return False
        plan = service.build_plan(waypoints, profile=profile, home_position=home_position)
        # The snapshot's controller_version is the post-install version
        # (observed + 1), matching the cutover path so version-tracking adapters
        # verify the install rather than rolling it back.
        observed = int(adapter.get_controller_state().controller_version or 0)
        snapshot = {"controller_version": observed + 1, "plan": plan}
        # Gate only the first install against the authorized version (CAS); later
        # segments build on the version this run wrote, so they pass None.
        expected = expected_controller_version if install_state["first"] else None
        result = adapter.install_mission(
            pending_snapshot=snapshot,
            expected_controller_version=expected,
        )
        if not result.ok:
            return False
        install_state["first"] = False
        return True

    return _drive
