from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from ai.migrations import apply_ai_store_migrations
from ai.mission_draft_service import MissionDraftService
from ai.mission_execution_service import MissionExecutionService
from ai.planning_shell_graph import (
    _build_retrieved_sources,
    _normalize_retrieval_request,
    finalize_response,
    store_draft,
    validate_draft,
)


class _FakeStore:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def add_message(self, session_id: str, **kwargs):
        self.calls.append({"session_id": session_id, **kwargs})
        return {"id": "m1", "session_id": session_id, **kwargs}


class _FakeRuntime:
    def __init__(self) -> None:
        self.ai_session_store = _FakeStore()


class _FakeGraphRuntime:
    def __init__(
        self,
        mission_execution_service: MissionExecutionService | None = None,
        draft_service: MissionDraftService | None = None,
    ) -> None:
        self.app_runtime = type(
            "_AppRuntime",
            (),
            {"mission_execution_service": mission_execution_service},
        )()
        self.draft_service = draft_service


def _make_mission_execution_service() -> tuple[MissionExecutionService, Path]:
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    tmp.close()
    db_path = Path(tmp.name)
    with sqlite3.connect(db_path) as conn:
        apply_ai_store_migrations(conn)
        conn.commit()
    return MissionExecutionService(db_path), db_path


def test_store_draft_uses_shared_id_for_revision_storage() -> None:
    svc, db_path = _make_mission_execution_service()
    draft_service = MissionDraftService(db_path)
    runtime = _FakeGraphRuntime(svc, draft_service=draft_service)
    state = {
        "session_id": "ai-session-123",
        "source_message_id": "msg-1",
        "intent": {"intent_type": "navigate_to_object"},
        "target_resolution": {},
        "draft": {
            "goal": "test mission",
            "waypoints": [{"x": 1.0, "y": 2.0, "z": 0.0}],
            "steps": [],
            "constraints": [],
            "assumptions": [],
            "risks": [],
            "required_operator_approval": True,
            "execution_allowed": False,
        },
        "validation": {"status": "warning", "warnings": [], "blockers": []},
        "approval_status": "awaiting_approval",
    }

    result = store_draft(state, {"configurable": {"runtime": runtime}})

    assert result["draft_id"].startswith("ai-draft-")
    revision = svc.get_revision(result["mission_revision_id"])
    assert revision is not None
    assert revision["draft_id"] == result["draft_id"]
    assert draft_service.get_draft(result["draft_id"]) is None


def test_build_retrieved_sources_reflects_enabled_controls() -> None:
    state = {
        "session_id": "ai-session-123",
        "retrieval_request": {
            "source_controls": {
                "project_docs": True,
                "mission_history": True,
                "replay_reports": False,
                "ai_chat_history": True,
                "settings_config": True,
                "sensor_context": False,
                "web_research": False,
            }
        },
        "settings_summary": {"settings_path": "config/settings.json"},
        "replay_summary": {},
    }

    sources = _build_retrieved_sources(state)
    source_names = [source["source"] for source in sources]

    assert source_names == [
        "project_docs",
        "mission_history",
        "ai_chat_history",
        "settings_config",
    ]


def test_finalize_response_for_draft_does_not_append_generation_failure() -> None:
    runtime = _FakeRuntime()
    state = {
        "session_id": "ai-session-123",
        "intent": {"intent_type": "navigate_to_object"},
        "draft_id": "ai-draft-123",
        "approval_status": "awaiting_approval",
        "validation": {"status": "warning", "warnings": ["telemetry stale"], "blockers": []},
        "errors": [],
        "tool_trace": [],
        "node_trace": [],
        "retrieval_request": _normalize_retrieval_request({"source_controls": {"project_docs": True}}),
        "retrieved_sources": [{"source": "project_docs", "status": "planned"}],
        "retrieval_citations": [{"source": "project_docs", "status": "planned"}],
    }

    finalize_response(state, {"configurable": {"runtime": runtime}})

    assert len(runtime.ai_session_store.calls) == 1
    content = runtime.ai_session_store.calls[0]["content"]
    meta = runtime.ai_session_store.calls[0]["meta"]
    assert "Mission draft created" in content
    assert "Could not generate a mission draft" not in content
    assert meta["retrieval_request"]["enabled_sources"] == ["project_docs", "mission_history", "replay_reports"]


def test_validate_draft_requests_clarification_for_edit_in_place_with_operator_edits() -> None:
    svc, _ = _make_mission_execution_service()
    proposal = svc.create_proposal(
        session_id="sess-1",
        source_message_id="msg-1",
        draft_id="draft-1",
        intent={},
        target_resolution={},
        draft_payload={
            "goal": "existing mission",
            "waypoints": [{"x": 0.0, "y": 0.0, "z": 0.0}, {"x": 1.0, "y": 1.0, "z": 0.0}],
            "steps": [],
            "constraints": [],
            "assumptions": [],
            "risks": [],
            "required_operator_approval": True,
            "execution_allowed": False,
        },
        validation={},
        draft_status="awaiting_approval",
    )
    svc.update_waypoint(
        proposal["id"],
        1,
        point={"x": 5.0, "y": 5.0, "z": 0.0},
        expected_version=0,
    )

    state = {
        "session_id": "sess-1",
        "intent": {},
        "target_resolution": {},
        "rover_state": {},
        "draft": {
            "goal": "refined mission",
            "waypoints": [{"x": 10.0, "y": 10.0, "z": 0.0}],
            "steps": [],
            "constraints": [],
            "assumptions": [],
            "risks": [],
            "required_operator_approval": True,
            "execution_allowed": False,
        },
        # ADR 0021 §3: the provenance-conflict gate fires only for edit_in_place
        # against the active mission (clone_and_edit preserves the original row, so
        # it can never clobber operator edits). Supply the explicit edit_in_place
        # contract: matching source/active mission id + operator edits present.
        "mission_edit_mode": "edit_in_place",
        "source_mission_id": "mission-1",
        "parent_operation_id": proposal["operation_id"],
        "active_mission_context": {
            "mission_id": "mission-1",
            "operation_id": proposal["operation_id"],
            "has_operator_edits": True,
        },
    }

    result = validate_draft(state, {"configurable": {"runtime": _FakeGraphRuntime(svc)}})

    assert result["clarification_request"]["type"] == "provenance_conflict"
    assert result["clarification_response"] == {}
    assert result["provenance_conflict"]["edited_waypoints"]
    assert any(error["code"] == "provenance_conflict" for error in result["errors"])


def test_validate_draft_allows_explicit_replace_confirmation() -> None:
    svc, _ = _make_mission_execution_service()
    proposal = svc.create_proposal(
        session_id="sess-1",
        source_message_id="msg-1",
        draft_id="draft-1",
        intent={},
        target_resolution={},
        draft_payload={
            "goal": "existing mission",
            "waypoints": [{"x": 0.0, "y": 0.0, "z": 0.0}, {"x": 1.0, "y": 1.0, "z": 0.0}],
            "steps": [],
            "constraints": [],
            "assumptions": [],
            "risks": [],
            "required_operator_approval": True,
            "execution_allowed": False,
        },
        validation={},
        draft_status="awaiting_approval",
    )
    svc.update_waypoint(
        proposal["id"],
        1,
        point={"x": 5.0, "y": 5.0, "z": 0.0},
        expected_version=0,
    )

    state = {
        "session_id": "sess-1",
        "intent": {},
        "target_resolution": {},
        "rover_state": {},
        "draft": {
            "goal": "refined mission",
            "waypoints": [{"x": 10.0, "y": 10.0, "z": 0.0}],
            "steps": [],
            "constraints": [],
            "assumptions": [],
            "risks": [],
            "required_operator_approval": True,
            "execution_allowed": False,
        },
        "parent_operation_id": proposal["operation_id"],
        "active_mission_context": {
            "operation_id": proposal["operation_id"],
            "has_operator_edits": True,
        },
        "clarification_response": {
            "answer": "replace the edited waypoints",
            "cancelled": False,
        },
    }

    result = validate_draft(state, {"configurable": {"runtime": _FakeGraphRuntime(svc)}})

    assert result["clarification_request"] == {}
    assert result["provenance_conflict"] == {}
    assert all(error["code"] != "provenance_conflict" for error in result["errors"])
