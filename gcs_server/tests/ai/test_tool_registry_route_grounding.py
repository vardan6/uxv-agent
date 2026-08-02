from __future__ import annotations

from types import SimpleNamespace

from ai.tool_registry import ToolInvocationContext, ToolRegistry
from tests.runtime_stub import make_stub_runtime


class _FakeRoadGraph:
    def __init__(self) -> None:
        self.calls: list[tuple[float, float, float, float]] = []

    def route_between(self, sx: float, sy: float, gx: float, gy: float) -> dict:
        self.calls.append((sx, sy, gx, gy))
        return {"ok": True, "waypoints": [{"x": sx, "y": sy, "z": 0.0}, {"x": gx, "y": gy, "z": 0.0}]}


def _context() -> ToolInvocationContext:
    return ToolInvocationContext(
        runtime=make_stub_runtime(),
        context_snapshot={},
        timezone_name="",
        permissions=frozenset(),
        source_controls={},
        session_id="chat-1",
        user_id="operator-1",
        run_mode="agent",
    )


def test_plan_route_between_accepts_explicit_coordinate_strings() -> None:
    registry = ToolRegistry()
    fake_graph = _FakeRoadGraph()
    registry._road_graph = fake_graph

    result = registry._plan_route_between(
        _context(),
        start_target="(44.0, 34.0)",
        goal_target="(60.0, 40.0)",
    )

    assert result["ok"] is True
    assert fake_graph.calls == [(44.0, 34.0, 60.0, 40.0)]


def test_plan_route_between_accepts_explicit_coordinate_dicts() -> None:
    registry = ToolRegistry()
    fake_graph = _FakeRoadGraph()
    registry._road_graph = fake_graph

    result = registry._plan_route_between(
        _context(),
        start_target={"x": 44.0, "y": 34.0},
        goal_target={"coordinates": [60.0, 40.0]},
    )

    assert result["ok"] is True
    assert fake_graph.calls == [(44.0, 34.0, 60.0, 40.0)]
