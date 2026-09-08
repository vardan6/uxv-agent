"""project_docs ingestion pipeline — dense+sparse hybrid (ADR 0028 §8/§9).

Usage (CLI):
    python -m rag.ingest [--docs-dir PATH] [--dry-run]
    python -m rag.ingest --backfill-sparse
    python -m rag.ingest --contextual [--contextual-model MODEL]

The CLI path reads connection params from env vars (below).  The app-triggered
path (Slice 1.6D) calls ``run_ingest(params, ...)`` directly after resolving
params from ``model_routing.embeddings`` via ``resolve_params_from_config``.

Env (CLI path only):
    UXV_EMBEDDINGS_BASE_URL  OpenAI-compatible base URL
                                      (default http://winhost:1234/v1 — LM Studio)
    UXV_EMBEDDINGS_MODEL     Embedding model id as the server exposes it
                                      (default qwen3-embedding-4b)
    UXV_EMBEDDINGS_DIM       Embedding dimension (default 2560)
    UXV_EMBEDDINGS_API_KEY   API key; LM Studio ignores it (default lm-studio)
    UXV_QDRANT_REST_PORT     Qdrant REST port (default 9004)
    UXV_CONTEXTUAL_MODEL     Chat model for contextual enrichment (--contextual)
    UXV_CONTEXTUAL_BASE_URL  Base URL for contextual chat (default: embeddings URL)
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rag.collection import collection_name_for

EMBED_BATCH_SIZE = 96
SPARSE_BATCH_SIZE = 128

_DEFAULT_BASE_URL = "http://winhost:1234/v1"
_DEFAULT_MODEL = "qwen3-embedding-4b"
_DEFAULT_DIM = 2560


# ---------------------------------------------------------------------------
# IngestParams — the single resolved bundle passed to the ingest core
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContextualConfig:
    """Config for LLM-based per-chunk context generation (Contextual Retrieval pattern)."""
    base_url: str
    model: str
    api_key: str


@dataclass(frozen=True)
class IngestParams:
    base_url: str
    model_id: str
    api_key: str
    dim: int
    collection: str


def resolve_params_from_env() -> IngestParams:
    """Build IngestParams from env vars (CLI path)."""
    base_url = os.environ.get("UXV_EMBEDDINGS_BASE_URL", _DEFAULT_BASE_URL).strip()
    model_id = os.environ.get("UXV_EMBEDDINGS_MODEL", _DEFAULT_MODEL).strip()
    dim = int(os.environ.get("UXV_EMBEDDINGS_DIM", str(_DEFAULT_DIM)))
    api_key = (os.environ.get("UXV_EMBEDDINGS_API_KEY", "lm-studio").strip() or "lm-studio")
    collection = collection_name_for(model_id, dim)
    return IngestParams(base_url=base_url, model_id=model_id, api_key=api_key, dim=dim, collection=collection)


def resolve_params_from_config(config: Any, *, secret_resolver: Any = None) -> IngestParams:
    """Build IngestParams from the app's model_routing.embeddings (app-triggered path).

    Requires backend to be importable (called from within the GCS process).
    The provider must have an ``embedding_dim`` field set in the config.
    """
    from backend.ai.provider_registry import resolve_embeddings_provider

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


def _embed_batch(texts: list[str], params: IngestParams) -> tuple[list[list[float]], int]:
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
    usage = getattr(response, "usage", None)
    tokens = int(getattr(usage, "total_tokens", 0) or getattr(usage, "prompt_tokens", 0) or 0)
    if tokens == 0:
        tokens = sum(len(t) for t in texts) // 4
    return embeddings, tokens


def _embed_all(texts: list[str], params: IngestParams) -> tuple[list[list[float]], int]:
    embeddings: list[list[float]] = []
    total_tokens = 0
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        batch_embeddings, batch_tokens = _embed_batch(batch, params)
        embeddings.extend(batch_embeddings)
        total_tokens += batch_tokens
    return embeddings, total_tokens


# ---------------------------------------------------------------------------
# Sparse encoding (in-process BM42 via fastembed)
# ---------------------------------------------------------------------------


def _sparse_encode(texts: list[str]) -> list[dict[str, list]] | None:
    """Encode texts into sparse vectors. Returns None if fastembed is unavailable."""
    try:
        from rag.sparse import get_encoder
        encoder = get_encoder()
        return encoder.encode(texts)
    except Exception as exc:  # noqa: BLE001
        print(f"  Warning: sparse encoding unavailable ({exc}); continuing dense-only.")
        return None


# ---------------------------------------------------------------------------
# Contextual Retrieval enrichment
# ---------------------------------------------------------------------------


_CONTEXTUAL_PROMPT_TMPL = """\
<document>
{doc}
</document>
Here is the chunk we want to situate within the whole document:
<chunk>
{chunk}
</chunk>
Please give a short succinct context to situate this chunk within the overall document \
for the purposes of improving search retrieval of the chunk. \
Answer only with the succinct context and nothing else."""


def _generate_context(doc_text: str, chunk_text: str, cfg: ContextualConfig) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
    prompt = _CONTEXTUAL_PROMPT_TMPL.format(doc=doc_text, chunk=chunk_text)
    response = client.chat.completions.create(
        model=cfg.model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
        temperature=0,
    )
    return (response.choices[0].message.content or "").strip()


def _enrich_chunks(
    chunks: list[Any],
    doc_text: str,
    cfg: ContextualConfig,
) -> list[tuple[Any, str]]:
    """Return [(chunk, enriched_text)] for each chunk with contextual prefix prepended."""
    enriched: list[tuple[Any, str]] = []
    for chunk in chunks:
        try:
            ctx = _generate_context(doc_text, chunk.text, cfg)
            enriched_text = f"{ctx}\n\n{chunk.text}" if ctx else chunk.text
        except Exception as exc:  # noqa: BLE001
            print(f"    Warning: contextual generation failed for chunk {chunk.chunk_index}: {exc}")
            enriched_text = chunk.text
        enriched.append((chunk, enriched_text))
    return enriched


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
    contextual_cfg: ContextualConfig | None = None,
) -> None:
    from rag.chunker import chunk_markdown_file
    from qdrant_client.models import PointIdsList, PointStruct

    chunks = chunk_markdown_file(file_path, rel_path)
    if not chunks:
        return

    existing = _scroll_path(client, params.collection, rel_path) if client is not None else {}
    use_contextual = contextual_cfg is not None

    to_embed: list[tuple[int, Any]] = []
    seen_ids: set[str] = set()

    for chunk in chunks:
        pid = _point_id(rel_path, chunk.chunk_index)
        seen_ids.add(pid)
        payload = existing.get(pid, {})
        hash_match = payload.get("content_hash") == chunk.content_hash
        mode_match = bool(payload.get("contextual")) == use_contextual
        if hash_match and mode_match:
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

    if dry_run:
        stats["upserted"] += len(to_embed)
        return

    # Contextual enrichment: call LLM to generate per-chunk context before embedding.
    if use_contextual:
        doc_text = file_path.read_text(encoding="utf-8", errors="replace")
        raw_chunks = [c for _, c in to_embed]
        enriched = _enrich_chunks(raw_chunks, doc_text, contextual_cfg)
        texts = [t for _, t in enriched]
    else:
        enriched = [(c, c.text) for _, c in to_embed]
        texts = [c.text for _, c in to_embed]

    embeddings, tokens = _embed_all(texts, params)
    stats["tokens"] = stats.get("tokens", 0) + tokens

    sparse_vecs = _sparse_encode(texts)

    points = []
    for (_, chunk), (_, embedded_text), embedding in zip(to_embed, enriched, embeddings):
        vector: dict[str, Any] = {"dense": embedding}
        if sparse_vecs is not None:
            from qdrant_client.models import SparseVector
            sv = sparse_vecs[len(points)]
            vector["sparse"] = SparseVector(indices=sv["indices"], values=sv["values"])
        points.append(PointStruct(
            id=_point_id(rel_path, chunk.chunk_index),
            vector=vector,
            payload={
                "source": "project_docs",
                "path": rel_path,
                "heading_path": chunk.heading_path,
                "chunk_index": chunk.chunk_index,
                "content_hash": chunk.content_hash,
                "text": embedded_text,
                "contextual": use_contextual,
            },
        ))

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
    contextual_cfg: ContextualConfig | None = None,
) -> dict[str, int]:
    """Ingest all markdown files under docs_dir into Qdrant using params.

    Returns stats dict with keys: upserted, skipped, deleted, tokens.
    """
    md_files = sorted(docs_dir.rglob("*.md"))
    print(f"Discovered {len(md_files)} markdown files in {docs_dir}")
    print(f"  collection: {params.collection}  model: {params.model_id}  dim: {params.dim}")
    if contextual_cfg:
        print(f"  contextual enrichment: ON  model: {contextual_cfg.model}")

    stats: dict[str, int] = {"upserted": 0, "skipped": 0, "deleted": 0, "tokens": 0}

    client = None
    if not dry_run:
        client = _qdrant_client(qdrant_port)
        _ensure_collection(client, params)

    for path in md_files:
        rel_path = str(path.relative_to(docs_dir.parent))
        _ingest_file(
            client, path, rel_path, params,
            dry_run=dry_run, stats=stats,
            contextual_cfg=contextual_cfg,
        )

    if not dry_run and client is not None:
        from rag.manifest import write_manifest
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
# Sparse backfill — populate sparse vectors on existing dense-only points
# ---------------------------------------------------------------------------


def backfill_sparse(
    params: IngestParams,
    *,
    dry_run: bool = False,
    qdrant_port: int = 9004,
) -> dict[str, int]:
    """Add sparse vectors to existing points that only have dense.

    Scrolls the collection, skips points that already have sparse or lack text
    payload, computes BM42 sparse in-process, and upserts updated points.
    """
    from qdrant_client.models import PointStruct, SparseVector
    from rag.sparse import get_encoder

    encoder = get_encoder()
    client = _qdrant_client(qdrant_port)
    stats = {"updated": 0, "skipped": 0}
    offset = None
    collection = params.collection

    print(f"Backfilling sparse vectors in '{collection}'...")

    while True:
        response, offset = client.scroll(
            collection_name=collection,
            with_payload=True,
            with_vectors=True,
            limit=100,
            offset=offset,
        )

        needs_sparse: list[Any] = []
        for point in response:
            vectors = point.vector if isinstance(point.vector, dict) else {}
            if "sparse" in vectors:
                stats["skipped"] += 1
                continue
            text = (point.payload or {}).get("text", "")
            if not text or (point.payload or {}).get("type") == "manifest":
                stats["skipped"] += 1
                continue
            needs_sparse.append(point)

        if needs_sparse and not dry_run:
            texts = [(p.payload or {}).get("text", "") for p in needs_sparse]
            sparse_vecs = encoder.encode(texts)
            updated: list[PointStruct] = []
            for point, sv in zip(needs_sparse, sparse_vecs):
                vectors = point.vector if isinstance(point.vector, dict) else {}
                updated.append(PointStruct(
                    id=point.id,
                    vector={
                        "dense": vectors.get("dense") or [],
                        "sparse": SparseVector(indices=sv["indices"], values=sv["values"]),
                    },
                    payload=point.payload or {},
                ))
            client.upsert(collection_name=collection, points=updated)

        stats["updated"] += len(needs_sparse)
        if offset is None:
            break

    return stats


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ingest project_docs into Qdrant")
    parser.add_argument("--docs-dir", help="Path to docs/ directory (default: auto-detected)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without embedding or upserting")
    parser.add_argument(
        "--backfill-sparse",
        action="store_true",
        help="Backfill BM42 sparse vectors into existing dense-only points; skip full ingest",
    )
    parser.add_argument(
        "--contextual",
        action="store_true",
        help="Prepend LLM-generated context to each chunk before embedding (Contextual Retrieval)",
    )
    parser.add_argument(
        "--contextual-model",
        help="Chat model for contextual enrichment (default: UXV_CONTEXTUAL_MODEL env)",
    )
    args = parser.parse_args(argv)

    params = resolve_params_from_env()
    port = int(os.environ.get("UXV_QDRANT_REST_PORT", "9004"))

    if args.backfill_sparse:
        dry_tag = " [dry-run]" if args.dry_run else ""
        stats = backfill_sparse(params, dry_run=args.dry_run, qdrant_port=port)
        print(f"Backfill done{dry_tag}: {stats['updated']} updated, {stats['skipped']} skipped.")
        return

    if args.docs_dir:
        docs_dir = Path(args.docs_dir).resolve()
    else:
        docs_dir = Path(__file__).parent.parent / "docs"

    if not docs_dir.is_dir():
        sys.exit(f"docs directory not found: {docs_dir}")

    contextual_cfg: ContextualConfig | None = None
    if args.contextual:
        model = (
            args.contextual_model
            or os.environ.get("UXV_CONTEXTUAL_MODEL", "").strip()
        )
        if not model:
            sys.exit(
                "Contextual mode requires a chat model. "
                "Set --contextual-model or UXV_CONTEXTUAL_MODEL."
            )
        base_url = os.environ.get("UXV_CONTEXTUAL_BASE_URL", "").strip() or params.base_url
        contextual_cfg = ContextualConfig(base_url=base_url, model=model, api_key=params.api_key)

    dry_tag = " [dry-run]" if args.dry_run else ""
    stats = run_ingest(
        params,
        docs_dir=docs_dir,
        dry_run=args.dry_run,
        qdrant_port=port,
        contextual_cfg=contextual_cfg,
    )
    print(
        f"Done{dry_tag}: {stats['upserted']} upserted, "
        f"{stats['skipped']} unchanged, "
        f"{stats['deleted']} deleted."
    )


if __name__ == "__main__":
    main()
