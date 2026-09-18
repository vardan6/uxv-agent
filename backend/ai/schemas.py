from __future__ import annotations

from typing import Any


INTENT_TYPES = frozenset({
    "navigate_to_object",
    "inspect_area",
    "search_area",
    "report_status",
    "compare_replay",
    "unknown",
})

SIDE_VALUES = frozenset({"left", "right", "front", "behind"})

REQUESTED_ACTION_VALUES = frozenset({"navigate", "inspect", "search", "report"})


def make_empty_intent() -> dict[str, Any]:
    return {
        "intent_type": "unknown",
        "summary": "",
        "target": {
            "description": "",
            "kind": None,
            "side": None,
            "min_distance_m": None,
            "max_distance_m": None,
            "relative_bearing_deg": None,
        },
        "area": {
            "description": None,
            "radius_m": None,
        },
        "requested_actions": [],
        "constraints": [],
        "requires_vehicle_motion": False,
        "requires_operator_approval": True,
        "missing_information": [],
        "confidence": 0.0,
    }


def validate_intent(intent: dict[str, Any]) -> list[str]:
    """Return a list of validation error strings. Empty list means valid."""
    errors: list[str] = []
    intent_type = str(intent.get("intent_type", "")).strip()
    if intent_type not in INTENT_TYPES:
        errors.append(f"intent_type '{intent_type}' must be one of {sorted(INTENT_TYPES)}")
    if not isinstance(intent.get("requested_actions"), list):
        errors.append("requested_actions must be a list")
    if not isinstance(intent.get("constraints"), list):
        errors.append("constraints must be a list")
    if not isinstance(intent.get("missing_information"), list):
        errors.append("missing_information must be a list")
    target = intent.get("target")
    if isinstance(target, dict):
        side = target.get("side")
        if side is not None and str(side).strip() not in SIDE_VALUES:
            errors.append(f"target.side '{side}' must be one of {sorted(SIDE_VALUES)} or null")
    confidence = intent.get("confidence")
    if confidence is not None:
        try:
            c = float(confidence)
            if not (0.0 <= c <= 1.0):
                errors.append("confidence must be between 0.0 and 1.0")
        except (TypeError, ValueError):
            errors.append("confidence must be a number")
    return errors
