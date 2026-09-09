"""One-off live verify for the read side of the RAG path (ADR 0028 §3/§8).

Loads the real GCS config, patches the `embeddings` routing provider's
`base_url` in-memory to the WSL2 gateway (LM Studio), then calls
`search_project_docs` and prints chunks + citations. Run-only; not a test.

    PYTHONPATH=<repo-root> .venv/bin/python -m rag.verify_query
"""

from __future__ import annotations

import sys

GATEWAY_BASE_URL = "http://172.25.240.1:1234/v1"
QUERIES = [
    "How does the mission executor run a behavior tree?",
    "What store backs the RAG project_docs collection?",
    "How are GPS coordinates handled as the master frame?",
]


def main() -> int:
    # Backend imports are confined to this CLI entrypoint (never a library
    # function importable from elsewhere), so no import-cycle risk exists at
    # module-load time — no injection needed here (see R2).
    from backend.config import load_config
    from backend.ai.provider_registry import resolve_embeddings_provider
    from backend.ai.retrieval import search_project_docs

    config = load_config()
    provider = resolve_embeddings_provider(config)
    old = provider.get("base_url")
    provider["base_url"] = GATEWAY_BASE_URL
    print(f"embeddings provider '{provider.get('id')}' base_url: {old} -> {GATEWAY_BASE_URL}")
    print(f"model_id: {provider.get('model_id')}\n")

    ok = True
    for q in QUERIES:
        res = search_project_docs(config, q, limit=3)
        print(f"Q: {q}")
        print(f"   available={res.get('available')} status={res.get('status')}")
        if not res.get("available"):
            print(f"   note: {res.get('note')}\n")
            ok = False
            continue
        for hit in res.get("results", []):
            hp = " > ".join(hit.get("heading_path") or [])
            print(f"   [{hit['score']:.3f}] {hit['ref']}  {hp}")
            snippet = (hit.get("text") or "").strip().replace("\n", " ")[:120]
            print(f"           {snippet}")
        print(f"   citations: {[c['ref'] for c in res.get('citations', [])]}\n")
        if not res.get("results"):
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
