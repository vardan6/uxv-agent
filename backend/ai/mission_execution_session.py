"""Construct a mode-aware behavior-tree executor from the live runtime
(ADR 0023 Phase 3).

This is the glue between the relocatable executor (:mod:`ai.mission_executor`)
and the GCS runtime. The executor itself imports no GCS internals; this builder
supplies its seams from runtime services:

* the execution mode is resolved from config (ADR 0021 §1);
* the ``leaf_driver`` is wired to the configured controller adapter via
  :func:`ai.mission_leaf_driver.make_controller_leaf_driver`;
* the mission's stored content (legacy flat waypoints or a behavior tree) is
  parsed into a :class:`ai.mission_tree.Node` root.

The AI execution tools (``arm_execution`` / ``execute_mission`` /
``cancel_execution`` / ``abort``) call this to obtain a ready executor; keeping
construction here means those tools never reach past the runtime seams.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

Clock = Callable[[], float]

# ActiveExecution.status values that will never change again.
TERMINAL_EXECUTION_STATUSES = frozenset(
    {"succeeded", "failed", "aborted", "cancelled", "expired", "error"}
)

from backend.ai.controller_mission_adapter import ControllerMissionAdapter
from backend.ai.execution_mode import CONFIRM, STRICT, resolve_execution_mode
from backend.ai.mission_executor import MissionExecutor, NodeStatus
from backend.ai.mission_leaf_driver import make_controller_leaf_driver
from backend.ai.mission_safety import parse_geofence
from backend.ai.mission_tree import Node, parse_mission_content


def build_mission_executor(
    runtime: Any,
    mission_content: Any,
    *,
    mode: Optional[str] = None,
    on_step: Optional[Any] = None,
    adapter: Optional[ControllerMissionAdapter] = None,
) -> tuple[MissionExecutor, Node]:
    """Build a :class:`MissionExecutor` ready to run ``mission_content``.

    ``mode`` defaults to the runtime-resolved execution mode (persisted setting,
    else the build-time default). Returns the executor paired with the parsed
    tree root so callers can ``executor.run(root)`` (or arm first, in Confirm
    mode). Raises :class:`ai.mission_tree.MissionTreeError` if the content is
    structurally invalid.
    """
    root = parse_mission_content(mission_content)

    if mode is None:
        mode = resolve_execution_mode(runtime.config)

    service = runtime.mission_execution_service
    if service is None:
        raise RuntimeError("runtime has no mission_execution_service; cannot drive the controller")

    # Defense-in-depth geofence (ADR 0023 Phase 5). Sourced from the mission
    # content under ``geofence`` (a parse_geofence to_dict shape). Enforcement
    # turns on *only* when a usable inclusion fence is present, so fenceless
    # missions keep running unchanged (a fail-closed validator would otherwise
    # refuse every fenceless mission). When present, the same fence is handed to
    # the leaf driver so the FC's authoritative layer is armed before driving.
    fence_dict = mission_content.get("geofence") if isinstance(mission_content, dict) else None
    fence = parse_geofence(fence_dict) if fence_dict else None
    enforce = bool(fence is not None and fence.is_usable)

    # Capture the controller version observed at authorization so the executor's
    # first segment install is CAS-gated against it (ADR 0020/0021): if a third
    # party mutates the controller between now and the run starting, the first
    # install fails rather than silently overwriting. The executor is sole writer
    # thereafter, so later segments don't re-assert. None when unreadable.
    expected_version: Optional[int] = None
    if adapter is None:
        adapter = service.controller_adapter
    try:
        expected_version = int(adapter.get_controller_state().controller_version or 0)
    except Exception:
        expected_version = None

    leaf_driver = make_controller_leaf_driver(
        adapter,
        geofence=fence_dict if enforce else None,
        expected_controller_version=expected_version,
    )

    executor = MissionExecutor(
        mode=mode,
        leaf_driver=leaf_driver,
        on_step=on_step,
        geofence=fence if enforce else None,
        enforce_geofence=enforce,
    )
    return executor, root


# ── Stateful per-session execution holder ────────────────────────────────────
#
# The AI execution tools (arm_execution / execute_mission / cancel_execution /
# abort) are independent tool calls, so the live executor and its arm/abort state
# must outlive any single call. This registry holds one in-flight execution per
# AI session. ``execute_mission`` runs the tree on a background thread so a later
# ``abort``/``cancel_execution`` call can cooperatively stop it (the executor
# honours ``request_abort`` between node steps).


@dataclass
class ActiveExecution:
    """One in-flight (or finished) mission run for a single AI session."""

    executor: MissionExecutor
    root: Node
    mission_id: str
    mode: str
    # prepared|armed|awaiting_confirm|running|succeeded|failed|aborted|cancelled|expired|error
    status: str = "prepared"
    detail: str = ""
    thread: Optional[threading.Thread] = field(default=None, repr=False)

    # Set whenever ``status`` changes; feeds the active-Mission inventory
    # (AR0a) so the safety view can show how long a Mission has sat in a state.
    last_transition_at: float = 0.0

    # Confirm-mode banner (ADR 0021 §1/§6): arm_confirm records a deadline; the
    # operator must confirm before it passes, else the run expires.
    confirm_timeout_s: int = 0
    confirm_deadline: float = 0.0

    # Injected so confirm-window expiry is deterministic under test; defaults to
    # the real wall clock for production use.
    clock: Clock = field(default=time.time, repr=False)

    def confirm_remaining_s(self) -> float:
        """Seconds left in the confirm window (0 once past the deadline)."""
        if self.status != "awaiting_confirm" or self.confirm_deadline <= 0:
            return 0.0
        return max(0.0, self.confirm_deadline - self.clock())

    def snapshot(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "mode": self.mode,
            "status": self.status,
            "detail": self.detail,
            "running": bool(self.thread and self.thread.is_alive()),
            "confirm_timeout_s": self.confirm_timeout_s,
            "confirm_deadline": self.confirm_deadline,
            "confirm_remaining_s": round(self.confirm_remaining_s(), 2),
            "last_transition_at": self.last_transition_at,
        }


class MissionExecutionSessions:
    """Thread-safe registry of the active :class:`MissionExecutor` per AI session.

    Keeps arm/abort/run state across the separate execution tool calls. One
    execution per session at a time; starting a new one while another is running
    is refused so two trees never drive the rover concurrently.
    """

    def __init__(self, *, clock: Clock = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._by_session: dict[str, ActiveExecution] = {}
        self._adapter_overrides: dict[str, ControllerMissionAdapter] = {}

    def get(self, session_id: str) -> Optional[ActiveExecution]:
        with self._lock:
            return self._by_session.get(_clean(session_id))

    def list_active(self) -> list[dict[str, Any]]:
        """Snapshot of every session-registry execution not yet terminal.

        Feeds the cross-session, cross-path active-Mission inventory (AR0a).
        A Mission driven only through the direct-controller cutover path has
        no entry here — see ``MissionExecutionService.list_active_controller_missions``.
        """
        with self._lock:
            items = list(self._by_session.items())
        return [
            {"session_id": session_id, **active.snapshot()}
            for session_id, active in items
            if active.status not in TERMINAL_EXECUTION_STATUSES
        ]

    def get_for_mission(self, mission_id: str) -> Optional[ActiveExecution]:
        target = _clean(mission_id)
        if not target:
            return None
        with self._lock:
            for active in self._by_session.values():
                if _clean(active.mission_id) == target:
                    return active
        return None

    # --- Session-scoped adapter overrides (Phase E) ---------------------------
    # Override the controller adapter used when building an executor for a
    # specific AI chat session. Reverts naturally when the session ends (in-memory,
    # keyed to session_id). Does not affect the global service adapter or sidebar.

    def set_adapter_override(self, session_id: str, adapter: ControllerMissionAdapter) -> None:
        with self._lock:
            self._adapter_overrides[_clean(session_id)] = adapter

    def clear_adapter_override(self, session_id: str) -> None:
        with self._lock:
            self._adapter_overrides.pop(_clean(session_id), None)

    def get_adapter_override(self, session_id: str) -> Optional[ControllerMissionAdapter]:
        with self._lock:
            return self._adapter_overrides.get(_clean(session_id))

    def prepare(
        self,
        session_id: str,
        *,
        executor: MissionExecutor,
        root: Node,
        mission_id: str,
        mode: str,
    ) -> ActiveExecution:
        """Register a freshly built executor for ``session_id``.

        Refuses to replace a run that is still in flight. ``status`` starts as
        ``armed`` when the executor was pre-armed (Confirm handshake), else
        ``prepared``.
        """
        key = _clean(session_id)
        with self._lock:
            existing = self._by_session.get(key)
            if existing is not None and existing.thread and existing.thread.is_alive():
                raise RuntimeError("an execution is already running for this session")
            active = ActiveExecution(
                executor=executor,
                root=root,
                mission_id=str(mission_id or ""),
                mode=str(mode or ""),
                status="armed" if getattr(executor, "_armed", False) else "prepared",
                clock=self._clock,
                last_transition_at=self._clock(),
            )
            self._by_session[key] = active
            return active

    def start(self, session_id: str) -> dict[str, Any]:
        """Run the prepared executor on a background thread. Returns a status
        snapshot immediately; the run resolves asynchronously."""
        active = self.get(session_id)
        if active is None:
            return {"ok": False, "error": "no prepared execution for this session"}
        with self._lock:
            if active.thread and active.thread.is_alive():
                return {"ok": False, "error": "execution already running", **active.snapshot()}
            active.status = "running"
            active.detail = ""
            active.last_transition_at = active.clock()

            def _run() -> None:
                try:
                    result = active.executor.run(active.root)
                    if result == NodeStatus.SUCCESS:
                        active.status = "succeeded"
                    elif result == NodeStatus.ABORTED:
                        active.status = "aborted"
                    else:
                        active.status = "failed"
                    active.detail = f"root -> {result.value}"
                except Exception as exc:  # ExecutorStateError or seam failure
                    active.status = "error"
                    active.detail = str(exc)
                active.last_transition_at = active.clock()

            thread = threading.Thread(
                target=_run, name=f"mission-exec-{_clean(session_id)}", daemon=True
            )
            active.thread = thread
            thread.start()
            return {"ok": True, **active.snapshot()}

    def arm(self, session_id: str) -> dict[str, Any]:
        active = self.get(session_id)
        if active is None:
            return {"ok": False, "error": "no prepared execution for this session"}
        active.executor.arm()
        active.status = "armed"
        active.last_transition_at = active.clock()
        return {"ok": True, **active.snapshot()}

    def arm_confirm(self, session_id: str, timeout_s: int) -> dict[str, Any]:
        """Confirm-mode handshake (ADR 0021 §1): arm the executor and open a
        bounded confirm window, but do NOT start. The operator confirms via
        :meth:`confirm` (the banner ``[Play]``) before the window passes; chat
        does not block while it is open."""
        active = self.get(session_id)
        if active is None:
            return {"ok": False, "error": "no prepared execution for this session"}
        active.executor.arm()
        active.confirm_timeout_s = int(timeout_s)
        active.confirm_deadline = self._clock() + float(timeout_s)
        active.status = "awaiting_confirm"
        active.detail = ""
        active.last_transition_at = active.clock()
        return {"ok": True, **active.snapshot()}

    def confirm(self, session_id: str) -> dict[str, Any]:
        """Operator ``[Play]`` on the confirm banner: start the run if still
        within the confirm window; otherwise mark it expired and refuse."""
        active = self.get(session_id)
        if active is None:
            return {"ok": False, "error": "no execution awaiting confirmation"}
        if active.status != "awaiting_confirm":
            return {"ok": False, "error": f"execution is not awaiting confirmation (status: {active.status})", **active.snapshot()}
        if active.confirm_remaining_s() <= 0:
            active.status = "expired"
            active.detail = "confirm window elapsed"
            active.last_transition_at = active.clock()
            return {"ok": False, "error": "confirm window elapsed", **active.snapshot()}
        return self.start(session_id)

    def cancel(self, session_id: str) -> dict[str, Any]:
        """Operator dismissed the banner (or cancel_execution): drop a prepared
        or awaiting-confirm run. A run already on a thread is left to ``abort``."""
        active = self.get(session_id)
        if active is None:
            return {"ok": False, "error": "no execution for this session"}
        if active.thread and active.thread.is_alive():
            return {"ok": False, "error": "execution already running; use abort", **active.snapshot()}
        active.status = "cancelled"
        active.confirm_deadline = 0.0
        active.last_transition_at = active.clock()
        return {"ok": True, **active.snapshot()}

    def request_abort(self, session_id: str) -> dict[str, Any]:
        active = self.get(session_id)
        if active is None:
            return {"ok": False, "error": "no execution for this session"}
        active.executor.request_abort()
        return {"ok": True, **active.snapshot()}

    # --- Mission-keyed variants (sidebar routes never expose session_id) ------

    def pause_for_mission(self, mission_id: str) -> dict[str, Any]:
        active = self.get_for_mission(mission_id)
        if active is None:
            return {"ok": False, "error": "no active execution for this mission"}
        if not (active.thread and active.thread.is_alive()):
            return {"ok": False, "error": "execution is not running", **active.snapshot()}
        active.executor.request_pause()
        active.status = "paused"
        active.last_transition_at = active.clock()
        return {"ok": True, **active.snapshot()}

    def resume_for_mission(self, mission_id: str) -> dict[str, Any]:
        active = self.get_for_mission(mission_id)
        if active is None:
            return {"ok": False, "error": "no active execution for this mission"}
        if active.status != "paused":
            return {"ok": False, "error": f"execution is not paused (status: {active.status})", **active.snapshot()}
        active.executor.resume()
        active.status = "running"
        active.last_transition_at = active.clock()
        return {"ok": True, **active.snapshot()}

    def abort_for_mission(self, mission_id: str) -> dict[str, Any]:
        active = self.get_for_mission(mission_id)
        if active is None:
            return {"ok": False, "error": "no active execution for this mission"}
        active.executor.request_abort()
        return {"ok": True, **active.snapshot()}


def _clean(session_id: Any) -> str:
    return str(session_id or "").strip()
