from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from ai.migrations import apply_ai_store_migrations
from ai.mission_draft_service import (
    MissionDraftService,
    validate_draft_payload,
    _draft_status_from_validation,
)

import sqlite3


def _make_db() -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    tmp.close()
    db_path = Path(tmp.name)
    with sqlite3.connect(db_path) as conn:
        apply_ai_store_migrations(conn)
        conn.commit()
    return db_path


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


def _empty_target_resolution() -> dict:
    return {"ok": False, "error": "no spatial target provided", "candidates": []}


# ---------------------------------------------------------------------------
# validate_draft_payload tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# draft_status_from_validation tests
# ---------------------------------------------------------------------------


class TestDraftStatusFromValidation:
    def test_blocked_maps_to_validation_failed(self):
        assert _draft_status_from_validation({"status": "blocked"}) == "validation_failed"

    def test_unsafe_maps_to_validation_failed(self):
        assert _draft_status_from_validation({"status": "unsafe"}) == "validation_failed"

    def test_needs_clarification_maps_correctly(self):
        assert _draft_status_from_validation({"status": "needs_clarification"}) == "needs_clarification"

    def test_warning_maps_to_awaiting_approval(self):
        assert _draft_status_from_validation({"status": "warning"}) == "awaiting_approval"

    def test_valid_maps_to_awaiting_approval(self):
        assert _draft_status_from_validation({"status": "valid"}) == "awaiting_approval"


# ---------------------------------------------------------------------------
# MissionDraftService CRUD tests
# ---------------------------------------------------------------------------


class TestMissionDraftService:
    def setup_method(self):
        self.db_path = _make_db()
        self.svc = MissionDraftService(self.db_path)
        self.session_id = "ai-session-test001"

    def _make_draft(self, requires_motion=False, with_target=False, **kwargs):
        intent = _base_intent(requires_motion=requires_motion, with_target=with_target)
        resolution = _resolved_target() if with_target else _empty_target_resolution()
        draft_payload = _base_draft()
        return self.svc.create_draft(
            session_id=self.session_id,
            intent=intent,
            target_resolution=resolution,
            draft_payload=draft_payload,
            **kwargs,
        )

    def test_create_returns_dict_with_id(self):
        draft = self._make_draft()
        assert draft["id"].startswith("ai-draft-")
        assert draft["session_id"] == self.session_id

    def test_execution_allowed_always_false(self):
        draft = self._make_draft()
        assert draft["draft"]["execution_allowed"] is False

    def test_clean_draft_status_awaiting_approval(self):
        draft = self._make_draft()
        assert draft["status"] == "awaiting_approval"

    def test_intent_and_validation_stored(self):
        draft = self._make_draft()
        assert isinstance(draft["intent"], dict)
        assert isinstance(draft["validation"], dict)
        assert draft["validation"]["status"] in ("valid", "warning", "awaiting_approval", "blocked", "needs_clarification")

    def test_get_draft(self):
        draft = self._make_draft()
        fetched = self.svc.get_draft(draft["id"])
        assert fetched is not None
        assert fetched["id"] == draft["id"]

    def test_get_nonexistent_draft_returns_none(self):
        assert self.svc.get_draft("ai-draft-doesnotexist") is None

    def test_list_drafts(self):
        for _ in range(3):
            self._make_draft()
        drafts = self.svc.list_drafts(session_id=self.session_id)
        assert len(drafts) == 3

    def test_list_drafts_status_filter(self):
        self._make_draft()
        drafts = self.svc.list_drafts(status_filter="awaiting_approval")
        assert all(d["status"] == "awaiting_approval" for d in drafts)

    def test_approve_draft(self):
        draft = self._make_draft()
        assert draft["status"] == "awaiting_approval"
        approved = self.svc.approve_draft(draft["id"], note="looks good")
        assert approved is not None
        assert approved["status"] == "approved"
        assert approved["approved_at"] is not None
        assert approved["approval_note"] == "looks good"

    def test_approve_non_awaiting_draft_returns_none(self):
        draft = self._make_draft()
        self.svc.approve_draft(draft["id"])
        result = self.svc.approve_draft(draft["id"])
        assert result is None

    def test_reject_draft(self):
        draft = self._make_draft()
        rejected = self.svc.reject_draft(draft["id"], note="not safe")
        assert rejected is not None
        assert rejected["status"] == "rejected"
        assert rejected["rejected_at"] is not None
        assert rejected["approval_note"] == "not safe"

    def test_reject_already_approved_returns_none(self):
        draft = self._make_draft()
        self.svc.approve_draft(draft["id"])
        result = self.svc.reject_draft(draft["id"])
        assert result is None

    def test_supersede_draft(self):
        draft = self._make_draft()
        assert self.svc.supersede_draft(draft["id"]) is True
        updated = self.svc.get_draft(draft["id"])
        assert updated["status"] == "superseded"

    def test_supersede_approved_draft_returns_false(self):
        draft = self._make_draft()
        self.svc.approve_draft(draft["id"])
        assert self.svc.supersede_draft(draft["id"]) is False

    def test_source_message_id_stored(self):
        draft = self._make_draft(source_message_id="ai-message-abc123")
        assert draft["source_message_id"] == "ai-message-abc123"

    def test_multiple_sessions_isolated(self):
        other_session = "ai-session-other001"
        self._make_draft()
        self.svc.create_draft(
            session_id=other_session,
            intent=_base_intent(),
            target_resolution={},
            draft_payload=_base_draft(),
        )
        mine = self.svc.list_drafts(session_id=self.session_id)
        theirs = self.svc.list_drafts(session_id=other_session)
        assert len(mine) == 1
        assert len(theirs) == 1
