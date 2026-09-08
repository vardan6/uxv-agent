"""TA7 — RAG job failures boundary (audit item 5).

`POST /api/rag/ingest` fans out to a background thread via
`gcs_server/routers/rag.py`'s in-memory `_IngestJobStore` / `_run_ingest_job`.
These tests exercise that job lifecycle directly: duplicate/concurrent jobs
for the same collection are rejected, a worker exception lands as an
observable terminal "error" status rather than crashing or hanging the
request thread, and a finished job frees its collection for a new run.
"""

from __future__ import annotations

import sys
import types

import pytest

import routers.rag as rag_router


def test_duplicate_job_for_same_collection_is_rejected() -> None:
    store = rag_router._IngestJobStore()

    first = store.create("docs-collection", "incremental")
    second = store.create("docs-collection", "incremental")

    assert first is not None
    assert second is None


def test_job_for_a_different_collection_is_not_blocked() -> None:
    store = rag_router._IngestJobStore()

    first = store.create("docs-collection", "incremental")
    other = store.create("other-collection", "incremental")

    assert first is not None
    assert other is not None


def test_finishing_a_job_frees_the_collection_for_a_new_run() -> None:
    store = rag_router._IngestJobStore()
    job = store.create("docs-collection", "incremental")
    assert job is not None

    store.finish(job)

    replacement = store.create("docs-collection", "incremental")
    assert replacement is not None


def test_worker_exception_is_recorded_as_terminal_error_status(monkeypatch: pytest.MonkeyPatch) -> None:
    # `_run_ingest_job` releases the collection lock through the module-level
    # `_job_store` singleton (not a store passed as a parameter), so swap
    # that singleton for an isolated instance rather than touching global
    # state shared with other tests.
    isolated_store = rag_router._IngestJobStore()
    monkeypatch.setattr(rag_router, "_job_store", isolated_store)

    job = isolated_store.create("docs-collection", "incremental")
    assert job is not None

    fake_ingest_module = types.ModuleType("rag_service.ingest")

    def _boom(params, docs_dir, qdrant_port):  # noqa: ARG001 - signature match
        raise RuntimeError("embedding provider unreachable")

    fake_ingest_module.run_ingest = _boom
    monkeypatch.setitem(sys.modules, "rag_service.ingest", fake_ingest_module)

    rag_router._run_ingest_job(job, params=object(), docs_dir="/tmp/docs", qdrant_port=1)

    snapshot = job.snapshot()
    assert snapshot["status"] == "error"
    assert "embedding provider unreachable" in snapshot["error"]
    assert snapshot["finished_at"] is not None

    # The job store must release the collection lock even on failure, or a
    # crashed ingest would permanently block all future runs for it.
    reopened = isolated_store.create("docs-collection", "incremental")
    assert reopened is not None
