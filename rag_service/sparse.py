"""In-process sparse encoder for hybrid search (ADR 0028 §4a).

Uses BM42 (fastembed) — lightweight attention-based sparse model that runs in-process
alongside dense embeddings (LM Studio is dense-only, so sparse must be local).
"""
from __future__ import annotations

SPARSE_MODEL = "Qdrant/bm42-all-minilm-l6-v2-attentions"

_instance: "_SparseEncoder | None" = None


class _SparseEncoder:
    def __init__(self, model_name: str = SPARSE_MODEL) -> None:
        try:
            from fastembed import SparseTextEmbedding
        except ImportError:
            raise ImportError("fastembed not installed. Run: pip install 'fastembed>=0.4.0'")
        print(f"  Loading sparse model '{model_name}' (first-use download if absent)...")
        self._model = SparseTextEmbedding(model_name=model_name)

    def encode(self, texts: list[str]) -> list[dict[str, list]]:
        """Return [{"indices": [...], "values": [...]}] for each input text."""
        results = []
        for emb in self._model.embed(texts):
            results.append({
                "indices": emb.indices.tolist(),
                "values": emb.values.tolist(),
            })
        return results


def get_encoder(model_name: str = SPARSE_MODEL) -> _SparseEncoder:
    global _instance
    if _instance is None:
        _instance = _SparseEncoder(model_name)
    return _instance
