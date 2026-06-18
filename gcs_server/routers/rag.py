"""RAG status and ingest endpoints (ADR 0028 §9 — Slice 1.6C/D)."""

from __future__ import annotations

import asyncio
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter()

_DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "docs"
_DEFAULT_QDRANT_PORT = 9004


def _qdrant_port() -> int:
    return int(os.environ.get("REMOTE_ROVER_QDRANT_REST_PORT", _DEFAULT_QDRANT_PORT))


def _runtime(request: Request) -> Any:
    return request.app.state.runtime


# ---------------------------------------------------------------------------
# In-memory ingest job store (Slice 1.6D)
# ---------------------------------------------------------------------------


class _IngestJob:
    def __init__(self, job_id: str, collection: str, mode: str) -> None:
        self.job_id = job_id
        self.collection = collection
        self.mode = mode
        self.status = "pending"
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.stats: dict[str, int] = {}
        self.error: str | None = None
        self._lock = threading.Lock()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "job_id": self.job_id,
                "collection": self.collection,
                "mode": self.mode,
                "status": self.status,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "stats": dict(self.stats),
                "error": self.error,
            }

    def _set(self, **kwargs: Any) -> None:
        with self._lock:
            for k, v in kwargs.items():
                setattr(self, k, v)


class _IngestJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, _IngestJob] = {}
        self._active_by_collection: dict[str, str] = {}
        self._lock = threading.Lock()

    def create(self, collection: str, mode: str) -> _IngestJob | None:
        """Create and register a new job; returns None if one is already active for the collection."""
        with self._lock:
            if collection in self._active_by_collection:
                return None
            job_id = f"rag-ingest-{uuid.uuid4().hex[:12]}"
            job = _IngestJob(job_id, collection, mode)
            self._jobs[job_id] = job
            self._active_by_collection[collection] = job_id
            return job

    def get(self, job_id: str) -> _IngestJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def finish(self, job: _IngestJob) -> None:
        with self._lock:
            if self._active_by_collection.get(job.collection) == job.job_id:
                del self._active_by_collection[job.collection]


_job_store = _IngestJobStore()


# ---------------------------------------------------------------------------
# Ingest worker (runs in a thread)
# ---------------------------------------------------------------------------


def _run_ingest_job(job: _IngestJob, params: Any, docs_dir: Path, qdrant_port: int) -> None:
    from rag_service.ingest import run_ingest

    job._set(status="running", started_at=datetime.now(timezone.utc).isoformat())
    try:
        if job.mode == "regenerate":
            try:
                from qdrant_client import QdrantClient
                client = QdrantClient(host="127.0.0.1", port=qdrant_port)
                existing = {c.name for c in client.get_collections().collections}
                if params.collection in existing:
                    client.delete_collection(params.collection)
            except Exception:  # noqa: BLE001
                pass

        stats = run_ingest(params, docs_dir=docs_dir, qdrant_port=qdrant_port)
        job._set(status="complete", stats=stats, finished_at=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        job._set(status="error", error=str(exc), finished_at=datetime.now(timezone.utc).isoformat())
    finally:
        _job_store.finish(job)


# ---------------------------------------------------------------------------
# GET /api/rag/status (Slice 1.6C)
# ---------------------------------------------------------------------------


@router.get("/api/rag/status")
async def rag_status(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    try:
        from rag_service.ingest import resolve_params_from_config
        secret_resolver = runtime.secret_store.get_secret if hasattr(runtime, "secret_store") else None
        params = resolve_params_from_config(runtime.config, secret_resolver=secret_resolver)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"Could not resolve embeddings config: {exc}"}, status_code=500)

    collection = params.collection
    model_id = params.model_id
    dim = params.dim

    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(host="127.0.0.1", port=_qdrant_port())
        existing = {c.name for c in client.get_collections().collections}

        if collection not in existing:
            return JSONResponse({
                "ok": True,
                "collection": collection,
                "model_id": model_id,
                "dim": dim,
                "exists": False,
                "point_count": 0,
                "last_ingest_at": None,
                "staleness": "missing",
            })

        coll_info = client.get_collection(collection)
        total_points = int(coll_info.points_count or 0)

        from rag_service.manifest import compute_staleness, read_manifest
        manifest = read_manifest(client, collection)
        stale_label = compute_staleness(
            manifest,
            expected_model_id=model_id,
            expected_dim=dim,
            docs_dir=_DOCS_DIR,
        )
        data_points = max(0, total_points - (1 if manifest is not None else 0))

        return JSONResponse({
            "ok": True,
            "collection": collection,
            "model_id": model_id,
            "dim": dim,
            "exists": True,
            "point_count": data_points,
            "last_ingest_at": (manifest or {}).get("last_ingest_at"),
            "staleness": stale_label,
        })
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"Qdrant unreachable: {exc}"}, status_code=503)


# ---------------------------------------------------------------------------
# POST /api/rag/ingest  +  GET /api/rag/ingest/{job_id}  (Slice 1.6D)
# ---------------------------------------------------------------------------


@router.post("/api/rag/ingest")
async def trigger_rag_ingest(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")

    mode = str(payload.get("mode", "incremental") or "incremental").strip().lower()
    if mode not in {"incremental", "regenerate"}:
        raise HTTPException(status_code=400, detail="mode must be 'incremental' or 'regenerate'")

    try:
        from rag_service.ingest import resolve_params_from_config
        secret_resolver = runtime.secret_store.get_secret if hasattr(runtime, "secret_store") else None
        params = resolve_params_from_config(runtime.config, secret_resolver=secret_resolver)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not resolve embeddings config: {exc}") from exc

    job = _job_store.create(params.collection, mode)
    if job is None:
        return JSONResponse(
            {"ok": False, "error": f"An ingest job is already running for collection '{params.collection}'"},
            status_code=409,
        )

    docs_dir = _DOCS_DIR
    qdrant_port = _qdrant_port()
    asyncio.create_task(asyncio.to_thread(_run_ingest_job, job, params, docs_dir, qdrant_port))

    return JSONResponse(
        {"ok": True, "job_id": job.job_id, "collection": params.collection, "mode": mode},
        status_code=202,
    )


@router.get("/api/rag/ingest/{job_id}")
async def get_ingest_job(job_id: str, request: Request) -> JSONResponse:
    job = _job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="ingest job not found")
    return JSONResponse({"ok": True, "job": job.snapshot()})
