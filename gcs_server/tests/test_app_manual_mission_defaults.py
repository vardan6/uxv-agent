from __future__ import annotations

from types import SimpleNamespace

from app import _default_manual_mission_name


def _runtime_with_ai_settings(ai_settings):
    return SimpleNamespace(config=SimpleNamespace(ai_settings=ai_settings))


def test_default_manual_mission_name_uses_lifecycle_setting() -> None:
    runtime = _runtime_with_ai_settings(
        {
            "mission_lifecycle": {
                "default_manual_mission_name": "Field Survey",
            }
        }
    )

    assert _default_manual_mission_name(runtime) == "Field Survey"


def test_default_manual_mission_name_falls_back_for_blank_setting() -> None:
    runtime = _runtime_with_ai_settings(
        {
            "mission_lifecycle": {
                "default_manual_mission_name": "   ",
            }
        }
    )

    assert _default_manual_mission_name(runtime) == "Untitled mission"
