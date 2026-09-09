"""rag.eval library-function tests (R2).

``_select_embeddings_provider`` and ``run_eval`` take their backend
dependencies (``resolve_provider`` / ``load_config`` / ``search_project_docs``)
as injected callables rather than importing backend directly — only
``main()`` (the CLI entrypoint) imports backend. These tests exercise the
library functions with fakes only, proving the rag -> backend import cycle is
broken: zero backend imports are needed to cover this logic.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from rag import eval as rag_eval


# ---------------------------------------------------------------------------
# _select_embeddings_provider
# ---------------------------------------------------------------------------


def _fake_config(providers: list[dict[str, Any]]) -> Any:
    return SimpleNamespace(llm_providers=providers)


def test_select_embeddings_provider_uses_explicit_provider_id() -> None:
    config = _fake_config([{"id": "a"}, {"id": "b"}])

    result = rag_eval._select_embeddings_provider(
        config, "b", resolve_provider=lambda cfg: {"id": "should-not-be-used"}
    )

    assert result == {"id": "b"}


def test_select_embeddings_provider_raises_for_unknown_explicit_id() -> None:
    config = _fake_config([{"id": "a"}])

    with pytest.raises(SystemExit, match="not found"):
        rag_eval._select_embeddings_provider(config, "missing", resolve_provider=lambda cfg: {"id": "a"})


def test_select_embeddings_provider_returns_routed_when_secret_free() -> None:
    config = _fake_config([{"id": "a", "auth_mode": "none"}])

    result = rag_eval._select_embeddings_provider(
        config, "", resolve_provider=lambda cfg: {"id": "a", "auth_mode": "none"}
    )

    assert result == {"id": "a", "auth_mode": "none"}


def test_select_embeddings_provider_falls_back_to_secret_free_when_routed_needs_secret(
    capsys: pytest.CaptureFixture[str],
) -> None:
    providers = [
        {"id": "routed", "capabilities": ["embeddings"], "auth_mode": "env_var"},
        {"id": "local", "capabilities": ["embeddings"], "auth_mode": "none", "enabled": True},
    ]
    config = _fake_config(providers)

    result = rag_eval._select_embeddings_provider(
        config, "", resolve_provider=lambda cfg: providers[0]
    )

    assert result == providers[1]
    assert "note:" in capsys.readouterr().out


def test_select_embeddings_provider_returns_routed_when_no_secret_free_alternative() -> None:
    providers = [{"id": "routed", "capabilities": ["embeddings"], "auth_mode": "env_var"}]
    config = _fake_config(providers)

    result = rag_eval._select_embeddings_provider(
        config, "", resolve_provider=lambda cfg: providers[0]
    )

    assert result == providers[0]


# ---------------------------------------------------------------------------
# run_eval
# ---------------------------------------------------------------------------


def _write_fixture(tmp_path: Path) -> Path:
    fixture = tmp_path / "eval_questions.yaml"
    fixture.write_text(
        """
defaults:
  limit: 5
  match: any
retrieval:
  - id: q1
    question: "does the executor run behavior trees?"
    expected_sources: ["design/executor.md"]
""".strip()
    )
    return fixture


def test_run_eval_reports_pass_when_expected_source_is_hit(tmp_path: Path) -> None:
    fixture_path = _write_fixture(tmp_path)
    provider = {"id": "local", "auth_mode": "none", "base_url": "http://x", "model_id": "m", "embedding_dim": 8}

    def fake_search_project_docs(config: Any, text: str, limit: int) -> dict[str, Any]:
        return {"available": True, "results": [{"path": "design/executor.md"}]}

    code = rag_eval.run_eval(
        fixture_path,
        load_config=lambda: SimpleNamespace(llm_providers=[provider], model_routing={}),
        search_project_docs=fake_search_project_docs,
        resolve_provider=lambda cfg: provider,
    )

    assert code == 0


def test_run_eval_reports_failure_when_expected_source_is_missing(tmp_path: Path) -> None:
    fixture_path = _write_fixture(tmp_path)
    provider = {"id": "local", "auth_mode": "none", "base_url": "http://x", "model_id": "m", "embedding_dim": 8}

    def fake_search_project_docs(config: Any, text: str, limit: int) -> dict[str, Any]:
        return {"available": True, "results": [{"path": "unrelated.md"}]}

    code = rag_eval.run_eval(
        fixture_path,
        load_config=lambda: SimpleNamespace(llm_providers=[provider], model_routing={}),
        search_project_docs=fake_search_project_docs,
        resolve_provider=lambda cfg: provider,
    )

    assert code == 1


def test_run_eval_returns_error_when_retrieval_unavailable(tmp_path: Path) -> None:
    fixture_path = _write_fixture(tmp_path)
    provider = {"id": "local", "auth_mode": "none", "base_url": "http://x", "model_id": "m", "embedding_dim": 8}

    def fake_search_project_docs(config: Any, text: str, limit: int) -> dict[str, Any]:
        return {"available": False, "status": "down", "note": "qdrant unreachable"}

    code = rag_eval.run_eval(
        fixture_path,
        load_config=lambda: SimpleNamespace(llm_providers=[provider], model_routing={}),
        search_project_docs=fake_search_project_docs,
        resolve_provider=lambda cfg: provider,
    )

    assert code == 1
