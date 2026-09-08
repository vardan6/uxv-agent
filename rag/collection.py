"""Collection naming for RAG project_docs — ADR 0028 §9.

The collection name encodes source, version, model slug, and dimension so a
model or dimension change is immediately visible and never silently aliases an
incompatible collection.

Naming convention:  {source}_v{version}_{model_slug}_{dim}
Example:            project_docs_v1_qwen3e4b_2560
"""

from __future__ import annotations

import re


def _model_slug(model_id: str) -> str:
    """Compact alphanumeric slug from a model id.

    Splits on non-alphanumeric separators, then:
    - Mixed alpha+digit tokens (e.g. "qwen3", "4b") → kept whole
    - Pure-alpha tokens (e.g. "embedding", "small") → first char only
    - Pure-digit tokens → kept whole

    Examples:
        "qwen3-embedding-4b"       → "qwen3e4b"
        "text-embedding-3-small"   → "te3s"
    """
    name = model_id.rsplit("/", 1)[-1].lower()
    tokens = re.split(r"[^a-z0-9]+", name)
    parts: list[str] = []
    for token in tokens:
        if not token:
            continue
        has_alpha = any(c.isalpha() for c in token)
        has_digit = any(c.isdigit() for c in token)
        if has_alpha and has_digit:
            parts.append(token)          # mixed — keep whole
        elif has_digit:
            parts.append(token)          # pure digit — keep whole
        else:
            parts.append(token[0])       # pure alpha — abbreviate to first char
    return "".join(parts)


def collection_name_for(model_id: str, dim: int, version: int = 1, source: str = "project_docs") -> str:
    """Return the canonical Qdrant collection name for the given embedding config.

    Args:
        model_id: Embedding model identifier (e.g. ``"qwen3-embedding-4b"``).
        dim:      Embedding dimension (e.g. ``2560``).
        version:  Schema version (increment on incompatible chunking/metadata changes).
        source:   RAG source name (default ``"project_docs"``).

    Returns:
        A deterministic collection name, e.g. ``"project_docs_v1_qwen3e4b_2560"``.
    """
    return f"{source}_v{version}_{_model_slug(model_id)}_{dim}"
