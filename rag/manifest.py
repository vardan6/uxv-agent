"""Qdrant sentinel manifest for RAG project_docs ingest state (ADR 0028 §9)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_MANIFEST_TYPE = "manifest"


def manifest_point_id(collection: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"rag:manifest:{collection}"))


def write_manifest(
    client: Any,
    collection: str,
    *,
    model_id: str,
    dim: int,
    upserted: int,
    skipped: int,
) -> None:
    """Upsert the sentinel manifest point at ingest end."""
    from qdrant_client.models import PointStruct

    now = datetime.now(timezone.utc).isoformat()
    client.upsert(
        collection_name=collection,
        points=[
            PointStruct(
                id=manifest_point_id(collection),
                vector={"dense": [0.0] * dim},
                payload={
                    "type": _MANIFEST_TYPE,
                    "collection": collection,
                    "model_id": model_id,
                    "dim": dim,
                    "last_ingest_at": now,
                    "upserted": upserted,
                    "skipped": skipped,
                },
            )
        ],
    )


def read_manifest(client: Any, collection: str) -> dict[str, Any] | None:
    """Fetch the sentinel manifest payload, or None if absent or Qdrant is unreachable."""
    try:
        results = client.retrieve(
            collection_name=collection,
            ids=[manifest_point_id(collection)],
            with_payload=True,
            with_vectors=False,
        )
        if results:
            return dict(results[0].payload or {})
    except Exception:  # noqa: BLE001
        pass
    return None


def compute_staleness(
    manifest: dict[str, Any] | None,
    *,
    expected_model_id: str,
    expected_dim: int,
    docs_dir: Path,
) -> str:
    """Return one of: ``up_to_date``, ``stale``, ``missing``, ``model_mismatch``."""
    if manifest is None:
        return "missing"
    manifest_model = str(manifest.get("model_id") or "").strip()
    manifest_dim = int(manifest.get("dim") or 0)
    if manifest_model != expected_model_id or manifest_dim != expected_dim:
        return "model_mismatch"
    last_ingest_str = str(manifest.get("last_ingest_at") or "").strip()
    if not last_ingest_str:
        return "missing"
    try:
        last_ingest = datetime.fromisoformat(last_ingest_str)
    except ValueError:
        return "missing"
    if docs_dir.is_dir():
        for md_file in docs_dir.rglob("*.md"):
            try:
                mtime = datetime.fromtimestamp(md_file.stat().st_mtime, tz=timezone.utc)
                if mtime > last_ingest:
                    return "stale"
            except OSError:
                pass
    return "up_to_date"
