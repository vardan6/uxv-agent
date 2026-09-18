from __future__ import annotations

import time
from typing import Any


_EXECUTION_LIKE_FIELDS = frozenset({"execute", "start", "publish", "send_command", "stage"})
_TELEMETRY_STALE_SECONDS = 30.0


def validate_draft_payload(
    intent: dict[str, Any],
    target_resolution: dict[str, Any],
    draft_payload: dict[str, Any],
    vehicle_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic validation of a mission draft.

    Returns a validation dict with status, blockers, warnings, and notes.
    Status values: valid, warning, needs_clarification, blocked, unsafe.
    """
    blockers: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    # execution_allowed must be false — hard blocker if someone snuck it in
    if draft_payload.get("execution_allowed") is True:
        blockers.append("execution_allowed must be false during AI mission drafting")

    # check for execution-like top-level fields in draft
    for field in _EXECUTION_LIKE_FIELDS:
        if field in draft_payload:
            blockers.append(f"draft contains disallowed execution field: '{field}'")

    # check steps for execution-like content
    for step in (draft_payload.get("steps") or []):
        if not isinstance(step, dict):
            continue
        for field in _EXECUTION_LIKE_FIELDS:
            if field in step:
                blockers.append(f"draft step contains disallowed execution field: '{field}'")

    # require operator approval for vehicle motion
    if intent.get("requires_vehicle_motion") and not draft_payload.get("required_operator_approval", True):
        blockers.append("required_operator_approval must be true when vehicle motion is involved")

    # spatial navigation requires resolved target
    requires_motion = bool(intent.get("requires_vehicle_motion"))
    has_spatial_target = _has_spatial_target(intent)
    if requires_motion and has_spatial_target:
        resolved = _target_resolved(target_resolution)
        if resolved == "blocked":
            blockers.append("spatial navigation requires a resolved target; scene or vehicle pose unavailable")
        elif resolved == "ambiguous":
            notes.append("spatial target is ambiguous; clarification may be needed")
            if not blockers:
                return _validation_result("needs_clarification", blockers, warnings, notes)

    # stale telemetry check
    if vehicle_state is not None:
        freshness = vehicle_state.get("freshness_seconds")
        if freshness is None:
            if requires_motion:
                warnings.append("vehicle telemetry freshness is unknown; draft risk elevated for motion tasks")
        elif float(freshness) > _TELEMETRY_STALE_SECONDS:
            if requires_motion:
                warnings.append(
                    f"vehicle telemetry is stale ({freshness:.0f}s old); "
                    "draft requires fresh vehicle pose before execution can be considered"
                )
            else:
                notes.append(f"vehicle telemetry is stale ({freshness:.0f}s old)")

    # unavailable scene data is a blocker for spatial missions
    if requires_motion and has_spatial_target:
        scene_ok = target_resolution.get("ok", False)
        scene_error = str(target_resolution.get("error", "")).lower()
        if not scene_ok and ("scene" in scene_error or "unavailable" in scene_error or "no pose" in scene_error):
            blockers.append("scene or map data unavailable; spatial mission cannot be validated")

    if blockers:
        status = "blocked"
    elif warnings:
        status = "warning"
    else:
        status = "valid"

    return _validation_result(status, blockers, warnings, notes)


def _has_spatial_target(intent: dict[str, Any]) -> bool:
    target = intent.get("target") or {}
    if not isinstance(target, dict):
        return False
    return any(
        target.get(k) not in (None, "")
        for k in ("description", "kind", "side", "relative_bearing_deg")
    )


def _target_resolved(target_resolution: dict[str, Any]) -> str:
    if not target_resolution.get("ok", False):
        error = str(target_resolution.get("error", "")).lower()
        if "unavailable" in error or "no pose" in error or "scene" in error:
            return "blocked"
        return "ambiguous"
    candidates = target_resolution.get("candidates") or target_resolution.get("objects") or []
    if len(candidates) == 0:
        return "ambiguous"
    return "resolved"


def _validation_result(
    status: str,
    blockers: list[str],
    warnings: list[str],
    notes: list[str],
) -> dict[str, Any]:
    return {
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "notes": notes,
        "validated_at": time.time(),
    }
