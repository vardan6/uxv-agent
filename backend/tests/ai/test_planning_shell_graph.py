from __future__ import annotations

from ai.retrieval import build_retrieved_sources, normalize_retrieval_request


def test_normalize_retrieval_request_splits_enabled_and_disabled_sources() -> None:
    result = normalize_retrieval_request(
        {
            "source_controls": {
                "project_docs": True,
                "mission_history": True,
                "replay_reports": False,
                "ai_chat_history": True,
                "settings_config": False,
                "sensor_context": False,
                "web_research": False,
            },
            "lazy_branches": ["retrieve_replay_context", ""],
            "request_scope": "operator_console",
        },
        session_id="ai-session-123",
    )

    assert result["session_id"] == "ai-session-123"
    assert result["enabled_sources"] == ["project_docs", "mission_history", "ai_chat_history"]
    assert result["disabled_sources"] == ["replay_reports", "settings_config", "sensor_context", "web_research"]
    assert result["lazy_branches"] == ["retrieve_replay_context"]
    assert result["request_scope"] == "operator_console"


def test_normalize_retrieval_request_defaults_for_non_dict_input() -> None:
    result = normalize_retrieval_request(None, session_id="ai-session-456")

    assert result["session_id"] == "ai-session-456"
    assert result["lazy_branches"] == []
    assert result["request_scope"] == "vehicle_task"


def test_build_retrieved_sources_reflects_enabled_controls() -> None:
    retrieval_request = normalize_retrieval_request(
        {
            "source_controls": {
                "project_docs": True,
                "mission_history": True,
                "replay_reports": False,
                "ai_chat_history": True,
                "settings_config": True,
                "sensor_context": False,
                "web_research": False,
            }
        }
    )

    sources = build_retrieved_sources(
        retrieval_request=retrieval_request,
        session_id="ai-session-123",
        settings_summary={"settings_path": "config/settings.json"},
        replay_summary={},
    )
    source_names = [source["source"] for source in sources]

    assert source_names == [
        "project_docs",
        "mission_history",
        "ai_chat_history",
        "settings_config",
    ]


def test_build_retrieved_sources_marks_lazy_branch_as_requested() -> None:
    retrieval_request = normalize_retrieval_request(
        {
            "source_controls": {
                "project_docs": False,
                "mission_history": False,
                "replay_reports": True,
                "ai_chat_history": False,
                "settings_config": False,
                "sensor_context": False,
                "web_research": False,
            },
            "lazy_branches": ["retrieve_replay_context"],
        }
    )

    sources = build_retrieved_sources(
        retrieval_request=retrieval_request,
        replay_summary={"summary": "drove 3 waypoints"},
    )

    assert sources == [
        {
            "source": "replay_reports",
            "kind": "replay",
            "available": True,
            "status": "loaded_summary",
            "requested": True,
            "note": "Replay summary was loaded lazily for this request.",
        }
    ]
