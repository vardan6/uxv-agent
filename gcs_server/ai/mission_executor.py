"""Relocatable server-side behavior-tree executor (ADR 0023, Phase 3).

ADR 0023 decision 2: a Mission's behavior tree is executed by a server-side
executor that drives the rover live over the existing transport, built as a
self-contained, relocatable module so it can later move onto a companion
computer for onboard autonomy. This module is that executor.

It walks a :mod:`ai.mission_tree` and drives the rover through three injected
seams — it never imports GCS internals directly, which is what keeps it
relocatable:

* ``leaf_driver(waypoints) -> bool`` — run one navigable segment (a ``nav_leaf``)
  on the vehicle. In the server phase this compiles the segment to ``.plan`` and
  uploads it via the controller adapter; on a companion computer it would drive
  the FC directly. Returns success/failure.
* ``condition_eval(name) -> bool`` — evaluate a named predicate for ``condition``
  nodes and loop ``while_condition`` guards.
* ``ask_operator(prompt, timeout_s) -> bool | None`` — pose an operator
  question and block until answered or ``timeout_s`` elapses; ``None`` means
  timed out (the node then resolves per its ``on_timeout``).

ADR 0023 decision 4 / ADR 0021 §1: the execution modes now gate a *continuous
control loop*, not a one-shot. :class:`MissionExecutor` enforces that gate at
``run`` time — Strict refuses to auto-run, Confirm requires a prior ``arm()``,
Autonomous runs freely. ``request_abort()`` is always honoured, cooperatively,
between node steps (the ``abort`` / ``cancel_execution`` tools are always bound).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from .execution_mode import AUTONOMOUS, CONFIRM, STRICT, normalize_mode
from .mission_safety import Geofence, FenceViolation, validate_waypoints
from .mission_tree import (
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

# Bounds the executor's own bookkeeping so a buggy/infinite loop guard cannot
# spin forever in the server phase; a real deployment tunes this.
_MAX_LOOP_ITERATIONS = 100_000


class NodeStatus(str, Enum):
    """Outcome of evaluating a node. The executor runs synchronously, so a node
    settles on SUCCESS or FAILURE; ABORTED propagates a cooperative cancel."""

    SUCCESS = "success"
    FAILURE = "failure"
    ABORTED = "aborted"


class ExecutorStateError(RuntimeError):
    """Raised when ``run`` is called in a way the current mode forbids (e.g.
    Confirm mode without a prior ``arm``, or Strict mode at all)."""


class GeofenceViolationError(ExecutorStateError):
    """Raised by the early pre-flight gate when a mission's nav waypoints breach
    the configured inclusion fence (or none is configured while enforcement is
    on). Defense-in-depth: the executor refuses *before* driving anything, so a
    breaching mission never reaches the FC. Subclasses :class:`ExecutorStateError`
    so existing ``run`` callers surface it the same way as a mode refusal."""

    def __init__(self, violations: list[FenceViolation]) -> None:
        self.violations = list(violations)
        reasons = ", ".join(sorted({v.reason for v in self.violations})) or "unknown"
        super().__init__(
            f"geofence pre-flight failed: {len(self.violations)} waypoint(s) breach "
            f"the fence ({reasons})"
        )


# Injected seams. Kept as plain callables (not classes) so the relocated build
# can supply lambdas/closures without importing this module's types.
LeafDriver = Callable[[list[dict[str, Any]]], bool]
ConditionEval = Callable[[str], bool]
AskOperator = Callable[[str, float], Optional[bool]]


@dataclass
class StepEvent:
    """One executor step, for the audit trail / live status feed."""

    node_id: str
    node_type: str
    status: NodeStatus
    detail: str = ""


@dataclass
class MissionExecutor:
    """Walks a behavior tree, driving the rover through the injected seams.

    ``mode`` is an ADR 0021 execution mode. The seams default to safe stubs so a
    partially-wired executor fails closed (every leaf fails) rather than
    pretending to drive the rover.
    """

    mode: str = STRICT
    leaf_driver: LeafDriver = lambda waypoints: False
    condition_eval: ConditionEval = lambda name: False
    ask_operator: AskOperator = lambda prompt, timeout_s: None
    on_step: Optional[Callable[[StepEvent], None]] = None

    # Defense-in-depth geofence (ADR 0023 Phase 5). The FC is authoritative; this
    # is the executor's *early* check. Off by default so a fenceless mission runs
    # unchanged until a fence is sourced; flip ``enforce_geofence`` on and supply
    # ``geofence`` to make ``run`` refuse breaching missions before driving.
    geofence: Optional[Geofence] = None
    enforce_geofence: bool = False

    _armed: bool = field(default=False, init=False)
    _abort: bool = field(default=False, init=False)
    _pause_event: threading.Event = field(default_factory=threading.Event, init=False)
    events: list[StepEvent] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.mode = normalize_mode(self.mode, default=STRICT)
        self._pause_event.set()  # "set" means running; "clear" means paused

    # -- lifecycle / mode gate (ADR 0021 §1, ADR 0023 decision 4) -------------

    def arm(self) -> None:
        """Confirm-mode handshake: the operator has confirmed; the next ``run``
        may proceed. No-op in Autonomous; meaningless in Strict (``run`` still
        refuses). Mirrors the ``arm_execution`` tool bound only in Confirm mode."""
        self._armed = True

    def request_abort(self) -> None:
        """Cooperatively stop execution before the next node step. Always
        honoured regardless of mode (the ``abort`` tool is always bound).
        Also unblocks any active pause so the abort flag is seen promptly."""
        self._abort = True
        self._pause_event.set()

    def request_pause(self) -> None:
        """Park execution between node steps. The executor thread blocks at the
        next inter-node check until :meth:`resume` is called."""
        self._pause_event.clear()

    def resume(self) -> None:
        """Unpark the executor after a :meth:`request_pause`."""
        self._pause_event.set()

    def _check_runnable(self) -> None:
        if self.mode == STRICT:
            raise ExecutorStateError(
                "strict mode: the executor cannot auto-run; operator must drive manually"
            )
        if self.mode == CONFIRM and not self._armed:
            raise ExecutorStateError("confirm mode: arm() must be called before run()")

    # -- execution ------------------------------------------------------------

    def run(self, root: Node) -> NodeStatus:
        """Execute a tree from its root, returning the root's status.

        Raises :class:`ExecutorStateError` if the current mode forbids running.
        Resets per-run state (events, abort flag) so one executor instance can
        run successive missions; ``_armed`` is consumed by a Confirm run."""
        self._check_runnable()
        self._preflight_geofence(root)
        self._abort = False
        self._pause_event.set()
        self.events = []
        status = self._tick(root)
        if self.mode == CONFIRM:
            # A Confirm-mode arm authorizes exactly one run.
            self._armed = False
        return status

    def _preflight_geofence(self, root: Node) -> None:
        """Fail closed before driving: collect every ``nav_leaf`` waypoint in the
        tree and validate it against the inclusion fence. No-op unless
        ``enforce_geofence`` is set. Raises :class:`GeofenceViolationError` on any
        breach (or when enforcement is on but no usable fence is configured)."""
        if not self.enforce_geofence:
            return
        waypoints = self._collect_nav_waypoints(root)
        violations = validate_waypoints(waypoints, self.geofence)
        if violations:
            raise GeofenceViolationError(violations)

    def _collect_nav_waypoints(self, node: Node) -> list[dict[str, Any]]:
        """Flatten all ``nav_leaf`` waypoints reachable from ``node``, in order."""
        if node.type == NAV_LEAF:
            return list(node.waypoints)
        waypoints: list[dict[str, Any]] = []
        for child in node.children:
            waypoints.extend(self._collect_nav_waypoints(child))
        return waypoints

    def _tick(self, node: Node) -> NodeStatus:
        if self._abort:
            return self._emit(node, NodeStatus.ABORTED, "aborted")
        # Block here while paused; request_abort() sets the event to unblock.
        self._pause_event.wait()
        if self._abort:
            return self._emit(node, NodeStatus.ABORTED, "aborted")

        if node.type == SEQUENCE:
            return self._tick_sequence(node)
        if node.type == FALLBACK:
            return self._tick_fallback(node)
        if node.type == LOOP:
            return self._tick_loop(node)
        if node.type == RECOVERY:
            return self._tick_recovery(node)
        if node.type == NAV_LEAF:
            return self._tick_nav_leaf(node)
        if node.type == CONDITION:
            return self._tick_condition(node)
        if node.type == ASK_OPERATOR:
            return self._tick_ask_operator(node)
        return self._emit(node, NodeStatus.FAILURE, f"unknown node type {node.type!r}")

    def _tick_sequence(self, node: Node) -> NodeStatus:
        # Succeed only if every child succeeds, in order; fail/abort short-circuit.
        for child in node.children:
            status = self._tick(child)
            if status is not NodeStatus.SUCCESS:
                return self._emit(node, status, "child did not succeed")
        return self._emit(node, NodeStatus.SUCCESS, "all children succeeded")

    def _tick_fallback(self, node: Node) -> NodeStatus:
        # Succeed on the first child that succeeds; abort short-circuits.
        for child in node.children:
            status = self._tick(child)
            if status is NodeStatus.SUCCESS:
                return self._emit(node, NodeStatus.SUCCESS, "a child succeeded")
            if status is NodeStatus.ABORTED:
                return self._emit(node, NodeStatus.ABORTED, "aborted")
        return self._emit(node, NodeStatus.FAILURE, "no child succeeded")

    def _tick_loop(self, node: Node) -> NodeStatus:
        child = node.children[0]
        iteration = 0
        while True:
            if self._abort:
                return self._emit(node, NodeStatus.ABORTED, "aborted")
            # while_condition gates entry; a false guard ends the loop OK.
            if node.while_condition and not self.condition_eval(node.while_condition):
                return self._emit(node, NodeStatus.SUCCESS, "while-condition false")
            if node.count != LOOP_INFINITE and iteration >= node.count:
                return self._emit(node, NodeStatus.SUCCESS, f"completed {iteration} iterations")
            if iteration >= _MAX_LOOP_ITERATIONS:
                return self._emit(node, NodeStatus.FAILURE, "loop iteration cap exceeded")

            status = self._tick(child)
            if status is NodeStatus.ABORTED:
                return self._emit(node, NodeStatus.ABORTED, "aborted")
            if status is NodeStatus.FAILURE:
                return self._emit(node, NodeStatus.FAILURE, "loop body failed")
            iteration += 1

    def _tick_recovery(self, node: Node) -> NodeStatus:
        guarded, recovery = node.children[0], node.children[1]
        status = self._tick(guarded)
        if status is NodeStatus.SUCCESS:
            return self._emit(node, NodeStatus.SUCCESS, "guarded branch succeeded")
        if status is NodeStatus.ABORTED:
            return self._emit(node, NodeStatus.ABORTED, "aborted")
        # Guard failed: run the recovery branch and report its outcome.
        recovery_status = self._tick(recovery)
        return self._emit(node, recovery_status, "ran recovery branch")

    def _tick_nav_leaf(self, node: Node) -> NodeStatus:
        ok = bool(self.leaf_driver(node.waypoints))
        return self._emit(
            node,
            NodeStatus.SUCCESS if ok else NodeStatus.FAILURE,
            f"drove {len(node.waypoints)} waypoint(s)",
        )

    def _tick_condition(self, node: Node) -> NodeStatus:
        result = bool(self.condition_eval(node.condition))
        if node.negate:
            result = not result
        return self._emit(
            node,
            NodeStatus.SUCCESS if result else NodeStatus.FAILURE,
            f"condition {node.condition!r} -> {result}",
        )

    def _tick_ask_operator(self, node: Node) -> NodeStatus:
        answer = self.ask_operator(node.prompt, node.timeout_s)
        if answer is None:
            # Timed out: resolve per the node's declared timeout policy.
            status = NodeStatus.SUCCESS if node.on_timeout == "success" else NodeStatus.FAILURE
            return self._emit(node, status, "operator timed out")
        return self._emit(
            node,
            NodeStatus.SUCCESS if answer else NodeStatus.FAILURE,
            "operator answered",
        )

    def _emit(self, node: Node, status: NodeStatus, detail: str) -> NodeStatus:
        event = StepEvent(node_id=node.id, node_type=node.type, status=status, detail=detail)
        self.events.append(event)
        if self.on_step is not None:
            self.on_step(event)
        return status
