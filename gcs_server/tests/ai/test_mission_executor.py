from __future__ import annotations

import threading

import pytest

from ai.execution_mode import AUTONOMOUS, CONFIRM, STRICT
from ai.mission_executor import (
    ExecutorStateError,
    GeofenceViolationError,
    MissionExecutor,
    NodeStatus,
)
from ai.mission_safety import FencePoint, Geofence
from ai.mission_tree import (
    ASK_OPERATOR,
    CONDITION,
    FALLBACK,
    LOOP,
    LOOP_INFINITE,
    NAV_LEAF,
    RECOVERY,
    SEQUENCE,
    Node,
)


def _nav_leaf(node_id: str, waypoints: list[dict] | None = None) -> Node:
    return Node(type=NAV_LEAF, id=node_id, waypoints=waypoints or [{"lat": 1.0, "lon": 2.0}])


# -- mode gate ------------------------------------------------------------


def test_strict_mode_refuses_run():
    executor = MissionExecutor(mode=STRICT, leaf_driver=lambda wps: True)
    with pytest.raises(ExecutorStateError):
        executor.run(_nav_leaf("a"))


def test_confirm_mode_requires_arm():
    executor = MissionExecutor(mode=CONFIRM, leaf_driver=lambda wps: True)
    with pytest.raises(ExecutorStateError):
        executor.run(_nav_leaf("a"))
    executor.arm()
    assert executor.run(_nav_leaf("a")) == NodeStatus.SUCCESS


def test_confirm_mode_consumes_arm_after_one_run():
    executor = MissionExecutor(mode=CONFIRM, leaf_driver=lambda wps: True)
    executor.arm()
    executor.run(_nav_leaf("a"))
    with pytest.raises(ExecutorStateError):
        executor.run(_nav_leaf("a"))


def test_autonomous_mode_runs_freely():
    executor = MissionExecutor(mode=AUTONOMOUS, leaf_driver=lambda wps: True)
    assert executor.run(_nav_leaf("a")) == NodeStatus.SUCCESS
    assert executor.run(_nav_leaf("b")) == NodeStatus.SUCCESS


# -- control flow -----------------------------------------------------------


def test_sequence_succeeds_only_if_all_children_succeed():
    executor = MissionExecutor(mode=AUTONOMOUS, leaf_driver=lambda wps: True)
    root = Node(type=SEQUENCE, id="root", children=[_nav_leaf("a"), _nav_leaf("b")])
    assert executor.run(root) == NodeStatus.SUCCESS

    failing = MissionExecutor(mode=AUTONOMOUS, leaf_driver=lambda wps: False)
    assert failing.run(root) == NodeStatus.FAILURE


def test_sequence_short_circuits_on_first_failure():
    calls: list[str] = []

    def leaf_driver(waypoints: list[dict]) -> bool:
        calls.append(waypoints[0].get("id", ""))
        return False

    executor = MissionExecutor(mode=AUTONOMOUS, leaf_driver=leaf_driver)
    root = Node(
        type=SEQUENCE,
        id="root",
        children=[
            _nav_leaf("a", [{"lat": 1, "lon": 1, "id": "a"}]),
            _nav_leaf("b", [{"lat": 2, "lon": 2, "id": "b"}]),
        ],
    )
    assert executor.run(root) == NodeStatus.FAILURE
    assert calls == ["a"]


def test_fallback_succeeds_on_first_success():
    outcomes = iter([False, True])
    executor = MissionExecutor(mode=AUTONOMOUS, leaf_driver=lambda wps: next(outcomes))
    root = Node(type=FALLBACK, id="root", children=[_nav_leaf("a"), _nav_leaf("b")])
    assert executor.run(root) == NodeStatus.SUCCESS


def test_fallback_fails_if_no_child_succeeds():
    executor = MissionExecutor(mode=AUTONOMOUS, leaf_driver=lambda wps: False)
    root = Node(type=FALLBACK, id="root", children=[_nav_leaf("a"), _nav_leaf("b")])
    assert executor.run(root) == NodeStatus.FAILURE


def test_loop_runs_fixed_count():
    calls = {"n": 0}

    def leaf_driver(waypoints: list[dict]) -> bool:
        calls["n"] += 1
        return True

    executor = MissionExecutor(mode=AUTONOMOUS, leaf_driver=leaf_driver)
    root = Node(type=LOOP, id="root", count=3, children=[_nav_leaf("a")])
    assert executor.run(root) == NodeStatus.SUCCESS
    assert calls["n"] == 3


def test_loop_while_condition_false_ends_loop_ok():
    executor = MissionExecutor(
        mode=AUTONOMOUS, leaf_driver=lambda wps: True, condition_eval=lambda name: False
    )
    root = Node(
        type=LOOP, id="root", count=LOOP_INFINITE, while_condition="keep_going", children=[_nav_leaf("a")]
    )
    assert executor.run(root) == NodeStatus.SUCCESS


def test_loop_body_failure_fails_loop():
    executor = MissionExecutor(mode=AUTONOMOUS, leaf_driver=lambda wps: False)
    root = Node(type=LOOP, id="root", count=5, children=[_nav_leaf("a")])
    assert executor.run(root) == NodeStatus.FAILURE


def test_recovery_runs_recovery_branch_on_guard_failure():
    guarded = _nav_leaf("guard")
    recovery = Node(type=CONDITION, id="recovery", condition="always_true")
    root = Node(type=RECOVERY, id="root", children=[guarded, recovery])

    executor = MissionExecutor(
        mode=AUTONOMOUS, leaf_driver=lambda wps: False, condition_eval=lambda name: True
    )
    assert executor.run(root) == NodeStatus.SUCCESS


def test_recovery_skips_recovery_branch_on_guard_success():
    executor = MissionExecutor(mode=AUTONOMOUS, leaf_driver=lambda wps: True)
    root = Node(type=RECOVERY, id="root", children=[_nav_leaf("guard"), _nav_leaf("recovery")])
    assert executor.run(root) == NodeStatus.SUCCESS
    assert [e.node_id for e in executor.events] == ["guard", "root"]


def test_condition_negate():
    executor = MissionExecutor(mode=AUTONOMOUS, condition_eval=lambda name: True)
    root = Node(type=CONDITION, id="root", condition="is_clear", negate=True)
    assert executor.run(root) == NodeStatus.FAILURE


def test_ask_operator_timeout_resolves_per_policy():
    executor_success = MissionExecutor(
        mode=AUTONOMOUS, ask_operator=lambda prompt, timeout_s: None
    )
    root_success = Node(type=ASK_OPERATOR, id="root", prompt="go?", on_timeout="success")
    assert executor_success.run(root_success) == NodeStatus.SUCCESS

    executor_failure = MissionExecutor(
        mode=AUTONOMOUS, ask_operator=lambda prompt, timeout_s: None
    )
    root_failure = Node(type=ASK_OPERATOR, id="root", prompt="go?", on_timeout="failure")
    assert executor_failure.run(root_failure) == NodeStatus.FAILURE


def test_ask_operator_answer():
    executor = MissionExecutor(mode=AUTONOMOUS, ask_operator=lambda prompt, timeout_s: True)
    root = Node(type=ASK_OPERATOR, id="root", prompt="go?")
    assert executor.run(root) == NodeStatus.SUCCESS


def test_nav_leaf_event_detail_reports_waypoint_count():
    executor = MissionExecutor(mode=AUTONOMOUS, leaf_driver=lambda wps: True)
    root = _nav_leaf("a", [{"lat": 1, "lon": 1}, {"lat": 2, "lon": 2}])
    executor.run(root)
    assert executor.events[-1].detail == "drove 2 waypoint(s)"


# -- abort / pause ----------------------------------------------------------


def test_request_abort_before_run_does_not_survive_into_the_run():
    # run() resets the abort flag as part of its per-run state reset, so an
    # abort requested before run() starts has no effect on that run.
    executor = MissionExecutor(mode=AUTONOMOUS, leaf_driver=lambda wps: True)
    executor.request_abort()
    root = Node(type=SEQUENCE, id="root", children=[_nav_leaf("a")])
    assert executor.run(root) == NodeStatus.SUCCESS


def test_abort_mid_run_via_on_step_callback_aborts_remaining_siblings():
    executor = MissionExecutor(mode=AUTONOMOUS, leaf_driver=lambda wps: True)

    def on_step(event):
        if event.node_id == "a":
            executor.request_abort()

    executor.on_step = on_step
    root = Node(type=SEQUENCE, id="root", children=[_nav_leaf("a"), _nav_leaf("b")])
    assert executor.run(root) == NodeStatus.ABORTED
    assert [(e.node_id, e.status) for e in executor.events] == [
        ("a", NodeStatus.SUCCESS),
        ("b", NodeStatus.ABORTED),
        ("root", NodeStatus.ABORTED),
    ]


def test_pause_requested_mid_run_blocks_the_next_tick_until_resume():
    executor = MissionExecutor(mode=AUTONOMOUS, leaf_driver=lambda wps: True)

    def on_step(event):
        if event.node_id == "a":
            executor.request_pause()

    executor.on_step = on_step
    root = Node(type=SEQUENCE, id="root", children=[_nav_leaf("a"), _nav_leaf("b")])
    result: dict[str, NodeStatus] = {}

    def _drive():
        result["status"] = executor.run(root)

    thread = threading.Thread(target=_drive, daemon=True)
    thread.start()
    thread.join(timeout=0.2)
    assert thread.is_alive()
    assert "status" not in result

    executor.resume()
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert result["status"] == NodeStatus.SUCCESS


def test_request_abort_unblocks_a_paused_run():
    executor = MissionExecutor(mode=AUTONOMOUS, leaf_driver=lambda wps: True)

    def on_step(event):
        if event.node_id == "a":
            executor.request_pause()

    executor.on_step = on_step
    root = Node(type=SEQUENCE, id="root", children=[_nav_leaf("a"), _nav_leaf("b")])
    result: dict[str, NodeStatus] = {}

    def _drive():
        result["status"] = executor.run(root)

    thread = threading.Thread(target=_drive, daemon=True)
    thread.start()
    thread.join(timeout=0.2)
    assert thread.is_alive()

    executor.request_abort()
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert result["status"] == NodeStatus.ABORTED


# -- geofence preflight -------------------------------------------------------


def _square_fence() -> Geofence:
    return Geofence(
        polygon=[
            FencePoint(lat=0.0, lon=0.0),
            FencePoint(lat=0.0, lon=1.0),
            FencePoint(lat=1.0, lon=1.0),
            FencePoint(lat=1.0, lon=0.0),
        ]
    )


def test_geofence_preflight_passes_waypoints_inside_fence():
    executor = MissionExecutor(
        mode=AUTONOMOUS,
        leaf_driver=lambda wps: True,
        geofence=_square_fence(),
        enforce_geofence=True,
    )
    root = _nav_leaf("a", [{"lat": 0.5, "lon": 0.5}])
    assert executor.run(root) == NodeStatus.SUCCESS


def test_geofence_preflight_refuses_waypoints_outside_fence():
    executor = MissionExecutor(
        mode=AUTONOMOUS,
        leaf_driver=lambda wps: True,
        geofence=_square_fence(),
        enforce_geofence=True,
    )
    root = _nav_leaf("a", [{"lat": 5.0, "lon": 5.0}])
    with pytest.raises(GeofenceViolationError):
        executor.run(root)


def test_geofence_disabled_ignores_out_of_fence_waypoints():
    executor = MissionExecutor(
        mode=AUTONOMOUS,
        leaf_driver=lambda wps: True,
        geofence=_square_fence(),
        enforce_geofence=False,
    )
    root = _nav_leaf("a", [{"lat": 5.0, "lon": 5.0}])
    assert executor.run(root) == NodeStatus.SUCCESS
