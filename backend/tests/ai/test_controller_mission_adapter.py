from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ai.controller_mission_adapter import (
    ControllerMissionAdapterError,
    MavlinkControllerMissionAdapter,
    _controller_version_for_items,
)


class _FakeMissionClient:
    def __init__(
        self,
        downloaded_sequences: list[list[dict]],
        upload_error: Exception | None = None,
        mode_error: Exception | None = None,
        parameters: dict[str, tuple[float, int]] | None = None,
    ) -> None:
        self._downloaded_sequences = [list(items) for items in downloaded_sequences]
        self._upload_error = upload_error
        self._mode_error = mode_error
        raw_parameters = {"MIS_RESTART": (0.0, 6)} if parameters is None else parameters
        self._parameters = {
            str(name).upper(): (float(value), int(param_type))
            for name, (value, param_type) in raw_parameters.items()
        }
        self.uploaded_items: list[list[dict]] = []
        self.mode_commands: list[str] = []
        self.mode_confirmations: list[tuple[str, float | None]] = []
        self.parameter_reads: list[str] = []
        self.parameter_sets: list[tuple[str, float, int]] = []
        self.download_calls = 0
        self.closed = False

    def download_mission_items(self) -> list[dict]:
        index = min(self.download_calls, len(self._downloaded_sequences) - 1)
        self.download_calls += 1
        return [dict(item) for item in self._downloaded_sequences[index]]

    def upload_mission_items(self, items: list[dict]) -> None:
        self.uploaded_items.append([dict(item) for item in items])
        if self._upload_error is not None:
            raise self._upload_error

    def set_mode(self, mode_name: str) -> None:
        self.mode_commands.append(mode_name)
        if self._mode_error is not None:
            raise self._mode_error

    def wait_for_mode(self, mode_name: str, *, timeout_s: float | None = None) -> None:
        self.mode_confirmations.append((mode_name, timeout_s))
        if self._mode_error is not None:
            raise self._mode_error

    def read_parameter(self, param_name: str) -> tuple[float, int]:
        normalized = str(param_name).upper()
        self.parameter_reads.append(normalized)
        if normalized not in self._parameters:
            raise ControllerMissionAdapterError(f"timed out waiting for parameter {normalized}")
        return self._parameters[normalized]

    def set_parameter(self, param_name: str, value: float, *, param_type: int) -> None:
        normalized = str(param_name).upper()
        self.parameter_sets.append((normalized, float(value), int(param_type)))
        self._parameters[normalized] = (float(value), int(param_type))

    def close(self) -> None:
        self.closed = True


def _temp_state_path() -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    return Path(tmp.name)


def _pending_snapshot() -> dict:
    return {
        "controller_version": 0,
        "operation_id": "op-1",
        "revision_id": "rev-1",
        "draft_id": "draft-1",
        "captured_at": 123.0,
        "mission_export": {"file_path": "/tmp/rev-1.plan"},
        "mission": {"goal": "survey"},
        "plan": {
            "mission": {
                "items": [
                    {
                        "frame": 3,
                        "command": 16,
                        "current": 1,
                        "autoContinue": True,
                        "params": [0, 0, 0, 0, 40.1, 44.5, 12.0],
                    }
                ]
            }
        },
    }


def test_mavlink_adapter_install_success_records_verified_snapshot() -> None:
    state_path = _temp_state_path()
    before_items = []
    after_items = [
        {
            "seq": 0,
            "frame": 3,
            "command": 16,
            "current": 1,
            "autocontinue": 1,
            "param1": 0.0,
            "param2": 0.0,
            "param3": 0.0,
            "param4": 0.0,
            "x": 401000000,
            "y": 445000000,
            "z": 12.0,
        }
    ]
    client = _FakeMissionClient([before_items, after_items])
    adapter = MavlinkControllerMissionAdapter(
        connection_url="udp:127.0.0.1:14550",
        state_path=state_path,
        client_factory=lambda: client,
    )

    result = adapter.install_mission(
        pending_snapshot=_pending_snapshot(),
        expected_controller_version=_controller_version_for_items(before_items),
    )

    assert result.ok is True
    assert result.status == "executing"
    assert result.controller_state.operation_id == "op-1"
    assert client.closed is True
    assert len(client.uploaded_items) == 1

    mapping = json.loads(state_path.read_text())
    assert len(mapping) == 1
    metadata = next(iter(mapping.values()))
    assert metadata["verified_snapshot"]["revision_id"] == "rev-1"
    assert metadata["verified_snapshot"]["draft_id"] == "draft-1"


def test_mavlink_adapter_rejects_stale_expected_controller_version() -> None:
    state_path = _temp_state_path()
    live_items = [
        {
            "seq": 0,
            "frame": 3,
            "command": 16,
            "current": 1,
            "autocontinue": 1,
            "param1": 0.0,
            "param2": 0.0,
            "param3": 0.0,
            "param4": 0.0,
            "x": 401000000,
            "y": 445000000,
            "z": 12.0,
        }
    ]
    client = _FakeMissionClient([live_items])
    adapter = MavlinkControllerMissionAdapter(
        connection_url="udp:127.0.0.1:14550",
        state_path=state_path,
        client_factory=lambda: client,
    )

    result = adapter.install_mission(pending_snapshot=_pending_snapshot(), expected_controller_version=12345)

    assert result.ok is False
    assert result.status == "stale_controller_version"
    assert client.uploaded_items == []
    assert client.closed is True


def test_mavlink_adapter_pause_switches_to_hold_and_confirms() -> None:
    client = _FakeMissionClient([[]])
    adapter = MavlinkControllerMissionAdapter(
        connection_url="udp:127.0.0.1:14550",
        state_path=_temp_state_path(),
        client_factory=lambda: client,
    )

    adapter.pause_mission()

    assert client.mode_commands == ["HOLD"]
    assert client.mode_confirmations == [("HOLD", 5.0)]
    assert client.closed is True


def test_mavlink_adapter_stop_switches_to_hold_and_confirms() -> None:
    client = _FakeMissionClient([[]])
    adapter = MavlinkControllerMissionAdapter(
        connection_url="udp:127.0.0.1:14550",
        state_path=_temp_state_path(),
        client_factory=lambda: client,
    )

    adapter.stop_mission()

    assert client.mode_commands == ["HOLD"]
    assert client.mode_confirmations == [("HOLD", 5.0)]
    assert client.closed is True


def test_mavlink_adapter_resume_switches_to_auto_and_confirms() -> None:
    client = _FakeMissionClient([[]])
    adapter = MavlinkControllerMissionAdapter(
        connection_url="udp:127.0.0.1:14550",
        state_path=_temp_state_path(),
        client_factory=lambda: client,
    )

    adapter.resume_mission()

    assert client.mode_commands == ["AUTO"]
    assert client.mode_confirmations == [("AUTO", 5.0)]
    assert client.closed is True


def test_mavlink_adapter_mode_switch_propagates_confirmation_error() -> None:
    client = _FakeMissionClient([[]], mode_error=RuntimeError("mode confirm failed"))
    adapter = MavlinkControllerMissionAdapter(
        connection_url="udp:127.0.0.1:14550",
        state_path=_temp_state_path(),
        client_factory=lambda: client,
    )

    try:
        adapter.pause_mission()
        assert False, "pause_mission should raise when mode confirmation fails"
    except RuntimeError as exc:
        assert str(exc) == "mode confirm failed"
    assert client.mode_commands == ["HOLD"]
    assert client.closed is True


def test_mavlink_adapter_asserts_mis_restart_resume_policy_before_mode_switch() -> None:
    client = _FakeMissionClient([[]], parameters={"MIS_RESTART": (1.0, 6)})
    adapter = MavlinkControllerMissionAdapter(
        connection_url="udp:127.0.0.1:14550",
        state_path=_temp_state_path(),
        client_factory=lambda: client,
    )

    adapter.resume_mission()

    assert client.parameter_reads == ["MIS_RESTART", "AUTO_RESUME"]
    assert client.parameter_sets == [("MIS_RESTART", 0.0, 6)]
    assert client.mode_commands == ["AUTO"]
    assert client.closed is True


def test_mavlink_adapter_asserts_auto_resume_policy_when_present() -> None:
    client = _FakeMissionClient([[]], parameters={"AUTO_RESUME": (0.0, 6)})
    adapter = MavlinkControllerMissionAdapter(
        connection_url="udp:127.0.0.1:14550",
        state_path=_temp_state_path(),
        client_factory=lambda: client,
    )

    adapter.pause_mission()

    assert client.parameter_reads == ["MIS_RESTART", "AUTO_RESUME"]
    assert client.parameter_sets == [("AUTO_RESUME", 1.0, 6)]
    assert client.mode_commands == ["HOLD"]
    assert client.closed is True


def test_mavlink_adapter_fails_closed_when_resume_policy_params_are_unavailable() -> None:
    client = _FakeMissionClient([[]], parameters={})
    adapter = MavlinkControllerMissionAdapter(
        connection_url="udp:127.0.0.1:14550",
        state_path=_temp_state_path(),
        client_factory=lambda: client,
    )

    try:
        adapter.pause_mission()
        assert False, "pause_mission should fail when resume-policy parameters are unavailable"
    except ControllerMissionAdapterError as exc:
        assert "MIS_RESTART or AUTO_RESUME" in str(exc)
    assert client.mode_commands == []
    assert client.closed is True
