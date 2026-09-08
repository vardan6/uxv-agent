from __future__ import annotations

from pathlib import Path

import pytest

from scene import scene_map


@pytest.fixture(autouse=True)
def clear_scene_cache() -> None:
    scene_map._load_scene_config.cache_clear()
    scene_map.get_scene_map_payload.cache_clear()
    yield
    scene_map._load_scene_config.cache_clear()
    scene_map.get_scene_map_payload.cache_clear()


@pytest.mark.parametrize(
    ("requested_size", "expected_size"),
    [
        (1, 32),
        (32, 32),
        (256, 256),
        (512, 256),
    ],
)
def test_scene_payload_clamps_grid_size_to_supported_boundaries(
    requested_size: int,
    expected_size: int,
) -> None:
    payload = scene_map.get_scene_map_payload(grid_size=requested_size)

    assert payload["grid_size"] == expected_size
    assert len(payload["heightmap"]) == expected_size
    assert all(len(row) == expected_size for row in payload["heightmap"])


def test_scene_payload_rejects_unsupported_backend() -> None:
    with pytest.raises(ValueError, match="Unsupported scene-map backend: unknown"):
        scene_map.get_scene_map_payload(backend="unknown")


def test_scene_payload_reports_missing_manifest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    missing_manifest = tmp_path / "missing-scene.json"
    monkeypatch.setattr(scene_map, "SCENE_CONFIG_PATH", missing_manifest)

    with pytest.raises(FileNotFoundError) as exc_info:
        scene_map.get_scene_map_payload()

    assert exc_info.value.filename == str(missing_manifest)
