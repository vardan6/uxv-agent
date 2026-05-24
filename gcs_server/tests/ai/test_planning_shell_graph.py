from __future__ import annotations

from ai.planning_shell_graph import _build_retrieved_sources, _normalize_retrieval_request, finalize_response


class _FakeStore:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def add_message(self, session_id: str, **kwargs):
        self.calls.append({"session_id": session_id, **kwargs})
        return {"id": "m1", "session_id": session_id, **kwargs}


class _FakeRuntime:
    def __init__(self) -> None:
        self.ai_session_store = _FakeStore()


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
