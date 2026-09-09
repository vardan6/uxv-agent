"""Golden-question eval for the RAG `project_docs` retrieval path.

A spot-check harness, not a test framework (RAG eval set, future-plans.md). For
each question in ``eval_questions.yaml`` it runs ``search_project_docs`` against
the live Qdrant collection and reports hit/miss on whether the expected source
document(s) appear in the top-k results. Pass/fail only — no ML scoring.

This is also the gate that lets us empirically confirm the agent tool-schema
trims (P3/P7/P8) do not degrade retrieval recall before/after a change.

Loads the real GCS config. App ``model_routing`` may point embeddings at a
provider that needs a stored secret the CLI runtime cannot resolve (and whose
vector dim may not match the ingested collection), so by default this picks the
first enabled, secret-free (``auth_mode: none``) embeddings provider in-memory
— typically the local LM Studio Qwen3 provider the collection was ingested with.
App config is never modified on disk. Use ``--provider <id>`` to force one.

    PYTHONPATH=<repo-root> .venv/bin/python -m rag.eval
    bin/rag eval

Exit code: 0 if every retrieval question passes, 1 otherwise (or on a setup
failure such as embeddings/Qdrant being unreachable).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

FIXTURE_PATH = Path(__file__).parent / "eval_questions.yaml"


def _load_fixture(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"eval fixture not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"eval fixture must be a mapping: {path}")
    return data


def _is_embeddings_provider(provider: dict[str, Any]) -> bool:
    caps = provider.get("capabilities") or []
    return isinstance(caps, list) and "embeddings" in caps


def _select_embeddings_provider(config: Any, provider_id: str) -> dict[str, Any]:
    """Pick the embeddings provider for the eval, preferring a secret-free local one.

    Order: explicit ``provider_id`` > the routed provider if it needs no secret >
    the first enabled secret-free embeddings provider. Returns the chosen provider
    dict; raises SystemExit with an actionable message if none is usable.
    """
    from backend.ai.provider_registry import resolve_embeddings_provider

    providers = [p for p in config.llm_providers if isinstance(p, dict)]
    if provider_id:
        match = next((p for p in providers if str(p.get("id")) == provider_id), None)
        if match is None:
            raise SystemExit(f"--provider '{provider_id}' not found in config.llm_providers")
        return match

    routed = resolve_embeddings_provider(config)
    if str(routed.get("auth_mode", "env_var")) == "none":
        return routed

    secret_free = [
        p for p in providers
        if _is_embeddings_provider(p)
        and p.get("enabled", True)
        and str(p.get("auth_mode", "env_var")) == "none"
    ]
    if secret_free:
        print(
            f"note: routed embeddings provider '{routed.get('id')}' needs a stored "
            f"secret (unavailable in CLI); using secret-free '{secret_free[0].get('id')}' instead."
        )
        return secret_free[0]
    return routed


def _hit_paths(result: dict[str, Any]) -> list[str]:
    return [str(hit.get("path") or "") for hit in result.get("results", [])]


def _evaluate_question(question: dict[str, Any], hit_paths: list[str]) -> tuple[bool, list[str]]:
    """Return (passed, missing_sources) for one retrieval question."""
    expected = [str(s).strip() for s in question.get("expected_sources") or [] if str(s).strip()]
    match = str(question.get("match") or "any").lower()
    found = [src for src in expected if any(src in path for path in hit_paths)]
    missing = [src for src in expected if src not in found]
    if not expected:
        return False, []
    passed = (len(missing) == 0) if match == "all" else (len(found) > 0)
    return passed, missing


def run_eval(
    fixture_path: Path = FIXTURE_PATH,
    *,
    limit_override: int | None = None,
    provider_id: str = "",
) -> int:
    from backend.config import load_config
    from backend.ai.retrieval import search_project_docs

    fixture = _load_fixture(fixture_path)
    defaults = fixture.get("defaults") if isinstance(fixture.get("defaults"), dict) else {}
    default_limit = limit_override or int(defaults.get("limit") or 5)
    default_match = str(defaults.get("match") or "any")
    questions = fixture.get("retrieval") or []
    if not isinstance(questions, list) or not questions:
        raise SystemExit("eval fixture has no `retrieval` questions")

    config = load_config()
    provider = _select_embeddings_provider(config, provider_id)
    # Route both query embedding and collection-name resolution at the chosen
    # provider for this run only (in-memory; on-disk config is untouched).
    config.model_routing["embeddings"] = {
        "primary_provider_id": str(provider.get("id")),
        "fallback_provider_ids": [],
    }
    print(
        f"embeddings provider '{provider.get('id')}' "
        f"(auth={provider.get('auth_mode', 'env_var')}, base_url={provider.get('base_url')})"
    )
    print(f"model_id: {provider.get('model_id')}  dim: {provider.get('embedding_dim')}\n")

    passed_count = 0
    failed: list[str] = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        qid = str(q.get("id") or "?")
        text = str(q.get("question") or "").strip()
        q.setdefault("match", default_match)
        limit = int(q.get("limit") or default_limit)

        res = search_project_docs(config, text, limit=limit)
        if not res.get("available"):
            # Setup-level failure (embeddings/Qdrant down, not ingested): abort
            # rather than report misleading per-question misses.
            print(f"[SETUP] {qid}: retrieval unavailable ({res.get('status')})")
            print(f"        {res.get('note')}")
            return 1

        hit_paths = _hit_paths(res)
        ok, missing = _evaluate_question(q, hit_paths)
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {qid}: {text}")
        for path in hit_paths:
            print(f"        - {path}")
        if ok:
            passed_count += 1
        else:
            failed.append(qid)
            print(f"        missing expected: {', '.join(missing) or '(none matched)'}")
        print()

    total = passed_count + len(failed)
    print(f"Retrieval: {passed_count}/{total} passed.")
    if failed:
        print(f"  failed: {', '.join(failed)}")

    trajectories = fixture.get("tool_trajectories") or []
    if isinstance(trajectories, list) and trajectories:
        print("\nManual tool-chaining checklist (not auto-scored — verify against a live agent):")
        for t in trajectories:
            if not isinstance(t, dict):
                continue
            tools = " -> ".join(str(x) for x in t.get("expected_tools") or [])
            print(f"  - {t.get('id')}: \"{t.get('prompt')}\"  expect: {tools}")

    return 0 if not failed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the RAG project_docs golden-question eval")
    parser.add_argument("--limit", type=int, default=None, help="Override top-k retrieval limit")
    parser.add_argument("--fixture", default=str(FIXTURE_PATH), help="Path to the eval fixture YAML")
    parser.add_argument(
        "--provider",
        default="",
        help="Force an embeddings provider id (default: prefer a secret-free one)",
    )
    args = parser.parse_args(argv)
    return run_eval(Path(args.fixture), limit_override=args.limit, provider_id=args.provider)


if __name__ == "__main__":
    sys.exit(main())
