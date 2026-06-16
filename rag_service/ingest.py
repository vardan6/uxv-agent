"""project_docs ingestion pipeline — dense-only slice 1 (ADR 0028 §8).

Usage:
    python -m rag_service.ingest [--docs-dir PATH] [--dry-run]

Embeds via an OpenAI-compatible endpoint (default: LM Studio serving
Qwen3-Embedding-4B). The endpoint + model MUST match the query-side `embeddings`
routing provider in the GCS config, or dense vectors land in different spaces.

Env:
    REMOTE_ROVER_EMBEDDINGS_BASE_URL  OpenAI-compatible base URL
                                      (default http://winhost:1234/v1 — LM Studio)
    REMOTE_ROVER_EMBEDDINGS_MODEL     Embedding model id as the server exposes it
                                      (default qwen3-embedding-4b)
    REMOTE_ROVER_EMBEDDINGS_API_KEY   API key; LM Studio ignores it (default lm-studio)
    REMOTE_ROVER_QDRANT_REST_PORT     Qdrant REST port (default 9004)
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path
from typing import Any

COLLECTION_NAME = "project_docs_v1_qwen3e4b_2560"
EMBEDDING_DIM = 2560
EMBED_BATCH_SIZE = 96

DEFAULT_EMBEDDINGS_BASE_URL = "http://winhost:1234/v1"
DEFAULT_EMBEDDINGS_MODEL = "qwen3-embedding-4b"


def _embeddings_base_url() -> str:
    return os.environ.get("REMOTE_ROVER_EMBEDDINGS_BASE_URL", DEFAULT_EMBEDDINGS_BASE_URL).strip()


def _embeddings_model() -> str:
    return os.environ.get("REMOTE_ROVER_EMBEDDINGS_MODEL", DEFAULT_EMBEDDINGS_MODEL).strip()


def _embeddings_api_key() -> str:
    # LM Studio ignores the key, but the OpenAI SDK requires a non-empty string.
    return os.environ.get("REMOTE_ROVER_EMBEDDINGS_API_KEY", "lm-studio").strip() or "lm-studio"


# ---------------------------------------------------------------------------
# Qdrant helpers
# ---------------------------------------------------------------------------


def _qdrant_client(port: int) -> Any:
    try:
        from qdrant_client import QdrantClient
    except ImportError:
        sys.exit("qdrant-client not installed. Run: pip install qdrant-client==1.18.0")
    return QdrantClient(host="127.0.0.1", port=port)


def _ensure_collection(client: Any) -> None:
    from qdrant_client.models import (
        Distance,
        SparseIndexParams,
        SparseVectorParams,
        VectorParams,
    )

    existing = {c.name for c in client.get_collections().collections}
    if COLLECTION_NAME in existing:
        return

    print(f"  Creating collection '{COLLECTION_NAME}' (dense {EMBEDDING_DIM} + sparse schema pre-provisioned)...")
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            "dense": VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE)
        },
        sparse_vectors_config={
            "sparse": SparseVectorParams(index=SparseIndexParams())
        },
    )


def _point_id(rel_path: str, chunk_index: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{rel_path}#{chunk_index}"))


def _scroll_path(client: Any, rel_path: str) -> dict[str, dict[str, Any]]:
    """Return {point_id: payload} for all points from this source file."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    result: dict[str, dict[str, Any]] = {}
    offset = None

    while True:
        response, offset = client.scroll(
            collection_name=COLLECTION_NAME,
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


def _embed_batch(texts: list[str], api_key: str) -> list[list[float]]:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=_embeddings_base_url())
    response = client.embeddings.create(model=_embeddings_model(), input=texts)
    embeddings = [item.embedding for item in response.data]
    for embedding in embeddings:
        if len(embedding) != EMBEDDING_DIM:
            sys.exit(
                f"Embedding dim mismatch: got {len(embedding)}, expected {EMBEDDING_DIM}. "
                f"Check REMOTE_ROVER_EMBEDDINGS_MODEL ('{_embeddings_model()}') matches a "
                f"{EMBEDDING_DIM}-dim model."
            )
    return embeddings


def _embed_all(texts: list[str], api_key: str) -> list[list[float]]:
    embeddings: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        embeddings.extend(_embed_batch(batch, api_key))
    return embeddings


# ---------------------------------------------------------------------------
# Per-file ingest
# ---------------------------------------------------------------------------


def _ingest_file(
    client: Any,
    file_path: Path,
    rel_path: str,
    api_key: str,
    *,
    dry_run: bool,
    stats: dict[str, int],
) -> None:
    from rag_service.chunker import chunk_markdown_file
    from qdrant_client.models import PointIdsList, PointStruct

    chunks = chunk_markdown_file(file_path, rel_path)
    if not chunks:
        return

    existing = _scroll_path(client, rel_path) if client is not None else {}

    to_embed: list[tuple[int, Any]] = []  # (list index, chunk)
    seen_ids: set[str] = set()

    for chunk in chunks:
        pid = _point_id(rel_path, chunk.chunk_index)
        seen_ids.add(pid)
        payload = existing.get(pid, {})
        if payload.get("content_hash") == chunk.content_hash:
            stats["skipped"] += 1
        else:
            to_embed.append((len(to_embed), chunk))

    # Delete stale points (removed chunks / shrunk files).
    stale = [pid for pid in existing if pid not in seen_ids]
    if stale and not dry_run:
        client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=PointIdsList(points=stale),
        )
    stats["deleted"] += len(stale)

    if not to_embed:
        return

    texts = [c.text for _, c in to_embed]

    if dry_run:
        stats["upserted"] += len(to_embed)
        return

    embeddings = _embed_all(texts, api_key)

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

    client.upsert(collection_name=COLLECTION_NAME, points=points)
    stats["upserted"] += len(points)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ingest project_docs into Qdrant")
    parser.add_argument("--docs-dir", help="Path to docs/ directory (default: auto-detected)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without embedding or upserting")
    args = parser.parse_args(argv)

    api_key = _embeddings_api_key()

    port = int(os.environ.get("REMOTE_ROVER_QDRANT_REST_PORT", "9004"))

    # Locate docs/ relative to this file (rag_service/ → repo root → docs/).
    if args.docs_dir:
        docs_dir = Path(args.docs_dir).resolve()
    else:
        docs_dir = Path(__file__).parent.parent / "docs"

    if not docs_dir.is_dir():
        sys.exit(f"docs directory not found: {docs_dir}")

    md_files = sorted(docs_dir.rglob("*.md"))
    print(f"Discovered {len(md_files)} markdown files in {docs_dir}")

    stats: dict[str, int] = {"upserted": 0, "skipped": 0, "deleted": 0}
    dry_tag = " [dry-run]" if args.dry_run else ""

    client = None
    if not args.dry_run:
        client = _qdrant_client(port)
        _ensure_collection(client)

    for path in md_files:
        rel_path = str(path.relative_to(docs_dir.parent))
        _ingest_file(client, path, rel_path, api_key, dry_run=args.dry_run, stats=stats)

    print(
        f"Done{dry_tag}: {stats['upserted']} upserted, "
        f"{stats['skipped']} unchanged, "
        f"{stats['deleted']} deleted."
    )


if __name__ == "__main__":
    main()
