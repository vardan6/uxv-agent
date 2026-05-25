from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ai.controller_mission_adapter import MavlinkControllerMissionAdapter, _controller_version_for_items


class _FakeMissionClient:
    def __init__(self, downloaded_sequences: list[list[dict]], upload_error: Exception | None = None) -> None:
        self._downloaded_sequences = [list(items) for items in downloaded_sequences]
        self._upload_error = upload_error
        self.uploaded_items: list[list[dict]] = []
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
