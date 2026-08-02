from __future__ import annotations

from ai.mission_draft_service import validate_draft_payload


def _base_intent(requires_motion: bool = False, with_target: bool = False) -> dict:
    intent = {
        "intent_type": "navigate_to_object" if requires_motion else "report_status",
        "summary": "test intent",
        "target": {
            "description": "the rock on the left" if with_target else "",
            "kind": None,
            "side": "left" if with_target else None,
            "min_distance_m": None,
            "max_distance_m": None,
            "relative_bearing_deg": None,
        },
        "area": {"description": None, "radius_m": None},
        "requested_actions": ["navigate"] if requires_motion else ["report"],
        "constraints": [],
        "requires_rover_motion": requires_motion,
        "requires_operator_approval": True,
        "missing_information": [],
        "confidence": 0.9,
    }
    return intent


def _base_draft(execution_allowed: bool = False) -> dict:
    return {
        "goal": "navigate to target",
        "target": {},
        "steps": [
            {"type": "navigate", "description": "move to object", "target": {}, "success_condition": "arrived"}
        ],
        "constraints": [],
        "assumptions": [],
        "risks": [],
        "required_operator_approval": True,
        "execution_allowed": execution_allowed,
    }


def _resolved_target() -> dict:
    return {"ok": True, "candidates": [{"id": "rock_1", "distance_m": 15.0, "side": "left"}]}


class TestValidateDraftPayload:
    def test_clean_non_motion_draft_is_valid(self):
        result = validate_draft_payload(_base_intent(), {}, _base_draft())
        assert result["status"] == "valid"
        assert result["blockers"] == []

    def test_execution_allowed_true_is_blocked(self):
        draft = _base_draft(execution_allowed=True)
        result = validate_draft_payload(_base_intent(), {}, draft)
        assert result["status"] == "blocked"
        assert any("execution_allowed" in b for b in result["blockers"])

    def test_disallowed_field_in_draft_is_blocked(self):
        draft = dict(_base_draft())
        draft["execute"] = True
        result = validate_draft_payload(_base_intent(), {}, draft)
        assert result["status"] == "blocked"
        assert any("execute" in b for b in result["blockers"])

    def test_disallowed_field_in_step_is_blocked(self):
        draft = dict(_base_draft())
        draft["steps"] = [{"type": "navigate", "publish": "cmd/start"}]
        result = validate_draft_payload(_base_intent(), {}, draft)
        assert result["status"] == "blocked"

    def test_motion_with_resolved_target_is_valid(self):
        intent = _base_intent(requires_motion=True, with_target=True)
        result = validate_draft_payload(intent, _resolved_target(), _base_draft())
        assert result["status"] in ("valid", "warning")
        assert not result["blockers"]

    def test_motion_with_no_target_resolution_is_needs_clarification(self):
        intent = _base_intent(requires_motion=True, with_target=True)
        resolution = {"ok": False, "error": "no candidates", "candidates": []}
        result = validate_draft_payload(intent, resolution, _base_draft())
        assert result["status"] == "needs_clarification"

    def test_spatial_scene_unavailable_is_blocked(self):
        intent = _base_intent(requires_motion=True, with_target=True)
        resolution = {"ok": False, "error": "scene unavailable", "candidates": []}
        result = validate_draft_payload(intent, resolution, _base_draft())
        assert result["status"] == "blocked"

    def test_stale_telemetry_produces_warning_for_motion(self):
        intent = _base_intent(requires_motion=True, with_target=True)
        rover_state = {"freshness_seconds": 120.0}
        result = validate_draft_payload(intent, _resolved_target(), _base_draft(), rover_state)
        assert result["status"] == "warning"
        assert any("stale" in w for w in result["warnings"])

    def test_fresh_telemetry_no_warning(self):
        intent = _base_intent(requires_motion=True, with_target=True)
        rover_state = {"freshness_seconds": 1.5}
        result = validate_draft_payload(intent, _resolved_target(), _base_draft(), rover_state)
        assert result["status"] in ("valid",)
        assert result["warnings"] == []

    def test_no_motion_no_target_resolution_still_valid(self):
        intent = _base_intent(requires_motion=False, with_target=False)
        result = validate_draft_payload(intent, {}, _base_draft())
        assert result["status"] == "valid"
