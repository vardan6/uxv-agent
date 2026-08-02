from __future__ import annotations

from ai.controller_mission_adapter import (
    ControllerMissionAdapterState,
    ControllerMissionInstallResult,
)
from ai.mission_leaf_driver import make_controller_leaf_driver


class _FakeControllerAdapter:
    """Minimal stand-in for the :class:`ControllerMissionAdapter` install port."""

    adapter_name = "fake"

    def __init__(self, *, controller_version: int = 0) -> None:
        self.controller_version = controller_version
        self.install_calls: list[dict] = []
        self.geofence_calls: list[dict] = []
        self.install_should_fail = False
        self.geofence_should_fail = False

    def get_controller_state(self) -> ControllerMissionAdapterState:
        return ControllerMissionAdapterState(controller_version=self.controller_version)

    def install_mission(
        self, *, pending_snapshot: dict, expected_controller_version: int | None = None
    ) -> ControllerMissionInstallResult:
        self.install_calls.append(
            {
                "pending_snapshot": pending_snapshot,
                "expected_controller_version": expected_controller_version,
            }
        )
        if self.install_should_fail:
            return ControllerMissionInstallResult(
                ok=False, status="rejected", controller_state=self.get_controller_state(), error="nope"
            )
        self.controller_version = int(pending_snapshot["controller_version"])
        return ControllerMissionInstallResult(
            ok=True, status="installed", controller_state=self.get_controller_state()
        )

    def upload_geofence(self, *, geofence: dict) -> ControllerMissionInstallResult:
        self.geofence_calls.append(geofence)
        if self.geofence_should_fail:
            return ControllerMissionInstallResult(
                ok=False, status="rejected", controller_state=self.get_controller_state(), error="nope"
            )
        return ControllerMissionInstallResult(
            ok=True, status="installed", controller_state=self.get_controller_state()
        )


_WAYPOINTS = [{"lat": 1.0, "lon": 2.0, "alt": 5.0}]


def test_empty_segment_is_a_no_op_success():
    adapter = _FakeControllerAdapter()
    driver = make_controller_leaf_driver(adapter)
    assert driver([]) is True
    assert adapter.install_calls == []


def test_installs_segment_and_advances_controller_version():
    adapter = _FakeControllerAdapter(controller_version=3)
    driver = make_controller_leaf_driver(adapter)
    assert driver(_WAYPOINTS) is True
    assert len(adapter.install_calls) == 1
    assert adapter.install_calls[0]["pending_snapshot"]["controller_version"] == 4
    assert adapter.controller_version == 4


def test_first_install_is_gated_against_expected_version_later_installs_are_not():
    adapter = _FakeControllerAdapter(controller_version=0)
    driver = make_controller_leaf_driver(adapter, expected_controller_version=0)
    assert driver(_WAYPOINTS) is True
    assert driver(_WAYPOINTS) is True
    assert adapter.install_calls[0]["expected_controller_version"] == 0
    assert adapter.install_calls[1]["expected_controller_version"] is None


def test_failed_first_install_keeps_the_version_gate_for_the_retry():
    adapter = _FakeControllerAdapter(controller_version=0)
    adapter.install_should_fail = True
    driver = make_controller_leaf_driver(adapter, expected_controller_version=0)
    assert driver(_WAYPOINTS) is False
    adapter.install_should_fail = False
    assert driver(_WAYPOINTS) is True
    assert adapter.install_calls[1]["expected_controller_version"] == 0


def test_geofence_uploaded_once_before_first_segment():
    adapter = _FakeControllerAdapter()
    fence = {"polygon": [{"lat": 0, "lon": 0}, {"lat": 0, "lon": 1}, {"lat": 1, "lon": 1}]}
    driver = make_controller_leaf_driver(adapter, geofence=fence)
    assert driver(_WAYPOINTS) is True
    assert driver(_WAYPOINTS) is True
    assert adapter.geofence_calls == [fence]


def test_failed_geofence_upload_fails_the_segment_closed():
    adapter = _FakeControllerAdapter()
    adapter.geofence_should_fail = True
    fence = {"polygon": [{"lat": 0, "lon": 0}, {"lat": 0, "lon": 1}, {"lat": 1, "lon": 1}]}
    driver = make_controller_leaf_driver(adapter, geofence=fence)
    assert driver(_WAYPOINTS) is False
    assert adapter.install_calls == []


def test_no_geofence_skips_upload_entirely():
    adapter = _FakeControllerAdapter()
    driver = make_controller_leaf_driver(adapter)
    driver(_WAYPOINTS)
    assert adapter.geofence_calls == []
