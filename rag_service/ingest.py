"""project_docs ingestion pipeline — dense-only slice 1 (ADR 0028 §8/§9).

Usage (CLI):
    python -m rag_service.ingest [--docs-dir PATH] [--dry-run]

The CLI path reads connection params from env vars (below).  The app-triggered
path (Slice 1.6D) calls ``run_ingest(params, ...)`` directly after resolving
params from ``model_routing.embeddings`` via ``resolve_params_from_config``.

Env (CLI path only):
    REMOTE_ROVER_EMBEDDINGS_BASE_URL  OpenAI-compatible base URL
                                      (default http://winhost:1234/v1 — LM Studio)
    REMOTE_ROVER_EMBEDDINGS_MODEL     Embedding model id as the server exposes it
                                      (default qwen3-embedding-4b)
    REMOTE_ROVER_EMBEDDINGS_DIM       Embedding dimension (default 2560)
    REMOTE_ROVER_EMBEDDINGS_API_KEY   API key; LM Studio ignores it (default lm-studio)
    REMOTE_ROVER_QDRANT_REST_PORT     Qdrant REST port (default 9004)
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rag_service.collection import collection_name_for

EMBED_BATCH_SIZE = 96

_DEFAULT_BASE_URL = "http://winhost:1234/v1"
_DEFAULT_MODEL = "qwen3-embedding-4b"
_DEFAULT_DIM = 2560


# ---------------------------------------------------------------------------
# IngestParams — the single resolved bundle passed to the ingest core
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IngestParams:
    base_url: str
    model_id: str
    api_key: str
    dim: int
    collection: str


def resolve_params_from_env() -> IngestParams:
    """Build IngestParams from env vars (CLI path)."""
    base_url = os.environ.get("REMOTE_ROVER_EMBEDDINGS_BASE_URL", _DEFAULT_BASE_URL).strip()
    model_id = os.environ.get("REMOTE_ROVER_EMBEDDINGS_MODEL", _DEFAULT_MODEL).strip()
    dim = int(os.environ.get("REMOTE_ROVER_EMBEDDINGS_DIM", str(_DEFAULT_DIM)))
    api_key = (os.environ.get("REMOTE_ROVER_EMBEDDINGS_API_KEY", "lm-studio").strip() or "lm-studio")
    collection = collection_name_for(model_id, dim)
    return IngestParams(base_url=base_url, model_id=model_id, api_key=api_key, dim=dim, collection=collection)


def resolve_params_from_config(config: Any, *, secret_resolver: Any = None) -> IngestParams:
    """Build IngestParams from the app's model_routing.embeddings (app-triggered path).

    Requires gcs_server to be importable (called from within the GCS process).
    The provider must have an ``embedding_dim`` field set in the config.
    """
    from gcs_server.ai.provider_registry import resolve_embeddings_provider

    provider = resolve_embeddings_provider(config, secret_resolver=secret_resolver)
    model_id = str(provider.get("model_id") or "").strip()
    if not model_id:
        raise ValueError("Routed embeddings provider has no model_id.")
    dim = provider.get("embedding_dim")
    if not dim:
        raise ValueError(
            f"Embeddings provider '{provider.get('id')}' has no embedding_dim field. "
            "Add 'embedding_dim' to the provider entry in your config."
        )
    dim = int(dim)
    base_url = str(provider.get("base_url") or "").strip()
    if not base_url:
        raise ValueError(f"Embeddings provider '{provider.get('id')}' has no base_url.")

    # Resolve API key via secret_resolver if available, else fall back to empty (no-auth providers).
    api_key = "lm-studio"
    secret_ref = str(provider.get("secret_ref") or "").strip()
    if secret_ref and secret_resolver is not None:
        try:
            api_key = secret_resolver(secret_ref) or api_key
        except Exception:  # noqa: BLE001
            pass

    collection = collection_name_for(model_id, dim)
    return IngestParams(base_url=base_url, model_id=model_id, api_key=api_key, dim=dim, collection=collection)


# ---------------------------------------------------------------------------
# Qdrant helpers
# ---------------------------------------------------------------------------


def _qdrant_client(port: int) -> Any:
    try:
        from qdrant_client import QdrantClient
    except ImportError:
        sys.exit("qdrant-client not installed. Run: pip install qdrant-client==1.18.0")
    return QdrantClient(host="127.0.0.1", port=port)


def _ensure_collection(client: Any, params: IngestParams) -> None:
    from qdrant_client.models import (
        Distance,
        SparseIndexParams,
        SparseVectorParams,
        VectorParams,
    )

    existing = {c.name for c in client.get_collections().collections}
    if params.collection in existing:
        return

    print(f"  Creating collection '{params.collection}' (dense {params.dim} + sparse schema pre-provisioned)...")
    client.create_collection(
        collection_name=params.collection,
        vectors_config={
            "dense": VectorParams(size=params.dim, distance=Distance.COSINE)
        },
        sparse_vectors_config={
            "sparse": SparseVectorParams(index=SparseIndexParams())
        },
    )


def _point_id(rel_path: str, chunk_index: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{rel_path}#{chunk_index}"))


def _scroll_path(client: Any, collection: str, rel_path: str) -> dict[str, dict[str, Any]]:
    """Return {point_id: payload} for all points from this source file."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    result: dict[str, dict[str, Any]] = {}
    offset = None

    while True:
        response, offset = client.scroll(
            collection_name=collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="path", match=MatchValue(value=rel_path))]
            ),
            with_payload=True,
            with_vectors=False,
            limit=256,
            offset=offset,
        )
        for point in response:
            result[str(point.id)] = point.payload or {}
        if offset is None:
            break

    return result


# ---------------------------------------------------------------------------
# OpenAI embedding
# ---------------------------------------------------------------------------


def _embed_batch(texts: list[str], params: IngestParams) -> list[list[float]]:
    from openai import OpenAI

    client = OpenAI(api_key=params.api_key, base_url=params.base_url)
    response = client.embeddings.create(model=params.model_id, input=texts)
    embeddings = [item.embedding for item in response.data]
    for embedding in embeddings:
        if len(embedding) != params.dim:
            sys.exit(
                f"Embedding dim mismatch: got {len(embedding)}, expected {params.dim}. "
                f"Check model '{params.model_id}' produces {params.dim}-dim vectors."
            )
    return embeddings


def _embed_all(texts: list[str], params: IngestParams) -> list[list[float]]:
    embeddings: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        embeddings.extend(_embed_batch(batch, params))
    return embeddings


# ---------------------------------------------------------------------------
# Per-file ingest
# ---------------------------------------------------------------------------


def _ingest_file(
    client: Any,
    file_path: Path,
    rel_path: str,
    params: IngestParams,
    *,
    dry_run: bool,
    stats: dict[str, int],
) -> None:
    from rag_service.chunker import chunk_markdown_file
    from qdrant_client.models import PointIdsList, PointStruct

    chunks = chunk_markdown_file(file_path, rel_path)
    if not chunks:
        return

    existing = _scroll_path(client, params.collection, rel_path) if client is not None else {}

    to_embed: list[tuple[int, Any]] = []
    seen_ids: set[str] = set()

    for chunk in chunks:
        pid = _point_id(rel_path, chunk.chunk_index)
        seen_ids.add(pid)
        payload = existing.get(pid, {})
        if payload.get("content_hash") == chunk.content_hash:
            stats["skipped"] += 1
        else:
            to_embed.append((len(to_embed), chunk))

    stale = [pid for pid in existing if pid not in seen_ids]
    if stale and not dry_run:
        client.delete(
            collection_name=params.collection,
            points_selector=PointIdsList(points=stale),
        )
    stats["deleted"] += len(stale)

    if not to_embed:
        return

    texts = [c.text for _, c in to_embed]

    if dry_run:
        stats["upserted"] += len(to_embed)
        return

    embeddings = _embed_all(texts, params)

    points = [
        PointStruct(
            id=_point_id(rel_path, chunk.chunk_index),
            vector={"dense": embedding},
            payload={
                "source": "project_docs",
                "path": rel_path,
                "heading_path": chunk.heading_path,
                "chunk_index": chunk.chunk_index,
                "content_hash": chunk.content_hash,
                "text": chunk.text,
            },
        )
        for (_, chunk), embedding in zip(to_embed, embeddings)
    ]

    client.upsert(collection_name=params.collection, points=points)
    stats["upserted"] += len(points)


# ---------------------------------------------------------------------------
# Core ingest (called by CLI and app-triggered paths)
# ---------------------------------------------------------------------------


def run_ingest(
    params: IngestParams,
    *,
    docs_dir: Path,
    dry_run: bool = False,
    qdrant_port: int = 9004,
) -> dict[str, int]:
    """Ingest all markdown files under docs_dir into Qdrant using params.

    Returns stats dict with keys: upserted, skipped, deleted.
    """
    md_files = sorted(docs_dir.rglob("*.md"))
    print(f"Discovered {len(md_files)} markdown files in {docs_dir}")
    print(f"  collection: {params.collection}  model: {params.model_id}  dim: {params.dim}")

    stats: dict[str, int] = {"upserted": 0, "skipped": 0, "deleted": 0}

    client = None
    if not dry_run:
        client = _qdrant_client(qdrant_port)
        _ensure_collection(client, params)

    for path in md_files:
        rel_path = str(path.relative_to(docs_dir.parent))
        _ingest_file(client, path, rel_path, params, dry_run=dry_run, stats=stats)

    if not dry_run and client is not None:
        from rag_service.manifest import write_manifest
        write_manifest(
            client,
            params.collection,
            model_id=params.model_id,
            dim=params.dim,
            upserted=stats["upserted"],
            skipped=stats["skipped"],
        )

    return stats


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ingest project_docs into Qdrant")
    parser.add_argument("--docs-dir", help="Path to docs/ directory (default: auto-detected)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without embedding or upserting")
    args = parser.parse_args(argv)

    params = resolve_params_from_env()
    port = int(os.environ.get("REMOTE_ROVER_QDRANT_REST_PORT", "9004"))

    if args.docs_dir:
        docs_dir = Path(args.docs_dir).resolve()
    else:
        docs_dir = Path(__file__).parent.parent / "docs"

    if not docs_dir.is_dir():
        sys.exit(f"docs directory not found: {docs_dir}")

    dry_tag = " [dry-run]" if args.dry_run else ""
    stats = run_ingest(params, docs_dir=docs_dir, dry_run=args.dry_run, qdrant_port=port)
    print(
        f"Done{dry_tag}: {stats['upserted']} upserted, "
        f"{stats['skipped']} unchanged, "
        f"{stats['deleted']} deleted."
    )


if __name__ == "__main__":
    main()
