# Remote Rover RAG Service

`rag_service/` is the **write side** of the RAG subsystem (ADR 0028): the Qdrant
sidecar, ingestion/chunking/embedding, and the update pipeline. The **read side**
(retrieval queried by the AI chat) lives in `gcs_server/ai/retrieval.py`.

Qdrant is the repo's first mandatory runtime container. The app **degrades
gracefully** without it — chat still works and `project_docs` reports
`available: false`.

## What is local vs pulled

- **Pulled once** from Docker Hub: the prebuilt `qdrant/qdrant` image (pinned in
  `docker-compose.yml`). We build no custom image.
- **Local on the host**: the repository's [`bin/rag`](../bin/rag) dispatcher,
  chunking/ingestion (Python in
  the repo venvs), and `qdrant-client`. Vector data persists in a Docker named
  volume (`remote-rover-qdrant-storage`).

## Quick start

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
bin/rag up        # start Qdrant (pulls the image on first run)
bin/rag status    # report readiness
bin/rag down      # stop (data volume preserved)
```

- Dashboard: <http://127.0.0.1:9004/dashboard>
- Health: <http://127.0.0.1:9004/healthz>

## Verbs

| Verb       | State        | Purpose                                            |
| ---------- | ------------ | -------------------------------------------------- |
| `up`       | this slice   | Start the Qdrant sidecar.                          |
| `down`     | this slice   | Stop the sidecar (named volume preserved).         |
| `status`   | this slice   | Report whether Qdrant is reachable.                |
| `ingest`   | this slice   | Incremental re-embed of changed chunks.            |
| `reindex`  | later slice  | Full rebuild (after a model/dimension change).     |

## Config

| Env var                             | Default | Meaning   |
| ----------------------------------- | ------- | --------- |
| `REMOTE_ROVER_QDRANT_REST_PORT`     | `9004`  | REST port (host) |
| `REMOTE_ROVER_QDRANT_GRPC_PORT`     | `9005`  | gRPC port (host) |
| `REMOTE_ROVER_EMBEDDINGS_BASE_URL`  | `http://winhost:1234/v1` | OpenAI-compatible embeddings endpoint (LM Studio) |
| `REMOTE_ROVER_EMBEDDINGS_MODEL`     | `qwen3-embedding-4b` | Embedding model id as the server exposes it |
| `REMOTE_ROVER_EMBEDDINGS_API_KEY`   | `lm-studio` | Ignored by LM Studio; SDK needs a non-empty value |

Host ports live in the project's 9000 range (GCS app is 9002); the container
keeps Qdrant's native `6333`/`6334` internally.

## Embeddings

The dense embedding model is **Qwen3-Embedding-4B** (2560-dim, Q8_0) served by
**LM Studio** over its OpenAI-compatible `/v1/embeddings` endpoint (ADR 0028
§4 / §4a). Ingest (write) and the query side (`gcs_server`'s `embeddings`
routing provider) **must point at the same endpoint + model** or dense vectors
land in different spaces. Collection: `project_docs_v1_qwen3e4b_2560`. Dense and
sparse are decoupled — sparse arrives in Slice 1.5 from a separate model
(in-process BGE-M3 / SPLADE), since LM Studio serves dense only.

Load the model in LM Studio, start its server, then:

```bash
PYTHONPATH=<repo-root> <repo-root>/.venv/bin/python -m rag_service.ingest
```

The equivalent repository command is `bin/rag ingest`.
