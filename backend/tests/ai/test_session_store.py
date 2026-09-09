from __future__ import annotations

from ai.session_store import AISessionStore, default_source_controls


def test_create_session_defaults_source_controls(tmp_path) -> None:
    store = AISessionStore(tmp_path / "ai.sqlite3")

    session = store.create_session()

    assert session["source_controls"] == default_source_controls()
    assert session["meta"]["source_controls"] == default_source_controls()


def test_update_session_source_controls_persists(tmp_path) -> None:
    store = AISessionStore(tmp_path / "ai.sqlite3")
    session = store.create_session()

    updated = store.update_session(
        session["id"],
        source_controls={
            "project_docs": True,
            "mission_history": False,
            "replay_reports": True,
            "ai_chat_history": True,
            "settings_config": True,
            "sensor_context": False,
            "web_research": True,
        },
    )

    reloaded = store.get_session(session["id"], include_messages=False)
    assert updated is not None
    assert reloaded is not None
    assert reloaded["source_controls"]["ai_chat_history"] is True
    assert reloaded["source_controls"]["mission_history"] is False
    assert reloaded["meta"]["source_controls"] == reloaded["source_controls"]
