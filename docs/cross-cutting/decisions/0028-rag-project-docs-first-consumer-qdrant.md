# 0028. RAG Ships: `project_docs` Is The First Consumer, On A Qdrant Sidecar

Date: 2026-06-15
Status: Accepted

## Context

[ADR 0003](./0003-rag-scope-vs-live-context.md) scoped RAG to the third
knowledge layer — documents, memory, history — never live state or geometry.
[ADR 0007](./0007-rag-later-not-now-for-live-state.md) then *deferred*
building it until a concrete consumer was named, and set the gate: "when a
concrete consumer is named, open a new ADR that scopes the RAG implementation
and supersedes this timing decision."

That consumer now exists. The AI chat already has the data-model plumbing —
`source_controls`, `build_retrieved_sources`, `build_retrieval_citations` in
`gcs_server/ai/retrieval.py` — but `project_docs` returns `available: false`
("RAG not wired"). The `docs/` tree (151 markdown files, ~2.4 MB: ADRs,
glossary, component design/requirements) is the natural first semantic-RAG
corpus: an operator or agent asking "why is RAG deferred" or "what is the
mission lifecycle" should get a grounded, cited answer instead of a stub.

This ADR scopes that implementation and supersedes ADR 0007's *timing*. ADR
0003's *scope* is unchanged: live state and geometry never go through RAG.

## Decision

**1. First consumer: `project_docs`.** Build one full vertical loop —
`docs/ → chunk → embed → vector store → retrieval tool → grounded answer →
citations` — before any other source. The remaining sources (`ai_chat_history`,
`replay_reports`, `mission_history`) are deferred to later slices; they slot
into the same subsystem without rearchitecting.

**2. Vector store: Qdrant as a Docker sidecar.** This is the repo's *first
mandatory runtime container* — a deliberate departure from the SQLite-only,
no-infra runtime. Chosen over in-process options (Chroma, sqlite-vec) because
the multi-source roadmap needs strong metadata filtering (per-operator
`ai_chat_history` scoping) and native hybrid (dense+sparse) search; chosen over
pgvector to avoid a Postgres migration. The dev-ergonomics cost is paid down by
operational tooling (see point 7) and graceful degradation: when Qdrant is
down, `project_docs` reports `available: false` exactly as today — chat still
works, RAG is simply unavailable.

**3. One subsystem, two halves, clean split:**
- **`rag_service/`** (new top-level sibling to `tts_service/`, `mav_sim/`) —
  the **write** side: ingestion, chunking, embedding (heavy/GPU deps isolated
  in the existing `.venv-gpu`), collection management, the update pipeline, and
  the Qdrant `docker-compose.yml`.
- **`gcs_server/ai/retrieval.py`** — the **read** side: a thin `qdrant-client`
  query path wired into the existing `source_controls` routing. No retrieval
  logic moves into `rag_service/`.

**4. Embeddings reuse the Provider / Model Routing abstraction.** The
`"embeddings"` routing purpose already exists (`provider_normalizers.py`); we
wire its call path. "Local vs API" is therefore a **routing config choice**,
not an architecture fork. The dense embedding model is **Qwen3-Embedding-4B**
(2560-dim, Q8_0 GGUF) served locally by **LM Studio** over its OpenAI-compatible
`/v1/embeddings` endpoint. Query-side dense embedding routes through the Provider
abstraction (`embeddings` routing purpose → an `lm_studio` embeddings provider);
ingest-side (`rag_service`) calls the same OpenAI-compatible endpoint directly.
The endpoint + model id MUST match on both sides or vectors land in different
spaces.

**4a. Dense and sparse are decoupled (amendment, 2026-06-15).** The original
plan used a single **unified** model (BGE-M3) for dense+sparse. That is dropped:
LM Studio / llama.cpp `/v1/embeddings` returns **dense vectors only** — it
cannot emit BGE-M3's sparse lexical weights or ColBERT vectors (those require
`FlagEmbedding` in-process). Choosing a stronger, larger dense model
(Qwen3-Embedding-4B, 2560-dim) therefore means **sparse becomes a separate
model**: Slice 1.5 adds sparse via in-process BGE-M3 or SPLADE in `rag_service`,
not via LM Studio. The hybrid plan (point 8) is preserved; only the
"one model emits both" assumption is replaced by a decoupled dense+sparse
architecture (a mainstream production pattern). Dimension is not quality — for a
~2.5k-chunk corpus 1024 vs 2560 dense is imperceptible; the larger model was an
informed preference, not a correctness requirement.

**5. Embedding identity is locked per collection; a model/dimension change
means a full re-index.** This is a hard invariant. Collection names encode
model + dimension + version (current dense collection:
`project_docs_v1_qwen3e4b_2560`) so a model swap produces a *new* collection
that can be built and swapped atomically — no silent dimension drift inside a
live collection.

**6. Chunking: header-aware markdown + metadata enrichment.** Split on heading
structure (ADR sections, glossary terms, design subsections); prepend the
heading path to the embedded text; size in **tokens** (target 700–1200, max
~1500–2000); add 10–15% overlap **only** when an oversized section must be
recursively split (no overlap between distinct sections; no overlap for prose).
Per-chunk metadata: `source`, `path`, `heading_path`, `chunk_index`, and a
`content_hash` that doubles as the idempotency key. Pure-LLM chunking is
rejected for v1 (unstable, costly, hard to diff); LLM enrichment arrives as
Contextual Retrieval in a later slice.

**7. Update pipeline: manual and idempotent; trigger is per-source.**
`project_docs` is pull-based — `./rag_service/bin/rag ingest` re-embeds only
changed chunks (detected via `content_hash`), making re-runs safe and cheap. No
watcher daemon, no cron. An opt-in `git post-commit` hook (default off) is
offered for convenience. Runtime sources (`ai_chat_history`, `mission_history`)
will get event-driven triggers when built — there is no universal trigger.

Operational surface is **thin bash, fat Python**: one dispatcher
`rag_service/bin/rag` with five verbs — `up | down | status | ingest |
reindex` — each a ~10-line wrapper that resolves the venv and delegates to a
Python module. `ingest` (incremental) and `reindex` (full rebuild, for use
after a model/dimension change) stay distinct verbs.

**8. The collection is provisioned for hybrid from day 1, populated dense-first.**
Slice 1 creates the collection with **both** dense and sparse vector configs but
populates only dense (Qwen3-Embedding-4B), and exposes one explicit
`search_project_docs` tool via `tool_registry.py` returning chunks + citations.
Slice 1.5 backfills sparse from a **separate** model (in-process BGE-M3 or
SPLADE — see point 4a) → **hybrid (RRF) + reranking** and adds **Contextual
Retrieval** (LLM-generated per-chunk context at ingest) — no collection
recreation required.

**9. Embedding management is operator-facing from Settings; identity, status,
and citations are operationalized (amendment, 2026-06-17).** Slice 1's CLI-only
ingest is extended into a managed surface, without changing the chunk-level
idempotency already shipped. The surface is a **dedicated "RAG" tab** in the
GCS Settings page — a new tab, not a section within an existing tab, because
the corpus/embedding concerns are a distinct operator domain from model config:

- **Single source of truth for the embedding model is the `embeddings` routing
  purpose.** Both the read side (`retrieval.py`) and the write side
  (`rag_service` ingest, when triggered from the app) resolve `base_url` +
  `model_id` from `model_routing.embeddings`. The collection name is **derived**
  from that model (`collection_name_for(model_id, dim, version)`) rather than
  hardcoded, making point 5's "model swap → new collection" automatic. The
  env-var defaults in `rag_service/ingest.py` survive only for standalone CLI use.
- **Per-collection manifest is a reserved Qdrant sentinel point** (fixed-UUID id,
  `kind: "__manifest__"`, excluded from search by filter): `embedding_model_id`,
  `base_url`, `dim`, `version`, `created_at`, `last_ingest_at`, `point_count`,
  and `files: {path: content_hash}`. Chosen over a SQLite table or JSON sidecar
  because it travels with the collection and resets atomically on
  drop/regenerate, so it cannot drift from the vectors it describes.
- **Ingest from Settings runs as an in-process async background job** (job id +
  progress poll) — embedding the full corpus takes minutes, so the trigger is
  non-blocking; one job per collection at a time. `incremental` reuses the
  existing `content_hash` skip/delete-stale path; `regenerate` drops and rebuilds.
- **Staleness is computed, not stored as status**: from the current routed model
  + the manifest, status is one of `up_to_date | stale | missing |
  model_mismatch`. A `missing`/`model_mismatch` collection for the *current*
  routed model is surfaced as an operator warning ("no matching embeddings
  collection — generate now"), directly satisfying the model-change-detection
  requirement.
- **Citations are rendered, not just returned.** `search_project_docs` already
  returns per-chunk `citations` (`path`, `heading_path`, `ref`). The assistant
  message carries them through to the UI, which renders both the model's inline
  prose links **and** a deterministic "Sources" footer. Each link targets the
  existing `/docs/{path}` viewer at the chunk's section via a heading-anchor
  slug derived from `heading_path` — so the viewer gains heading-id anchors.

**9a. RAG tab is a multi-model management surface; collections persist per model
(amendment, 2026-06-17).** The RAG tab gains an embedding model selector that
is the primary control surface for `model_routing.embeddings` — consistent with
the AI chat provider dropdown, which is the primary selector for the active chat
provider. Changing the selector saves the routing and immediately triggers a
status refresh (spinner → result within ~500 ms); no manual refresh step.

- **Collections persist per model and coexist in Qdrant.** Switching models
  does not destroy another model's collection. Each collection is owned by the
  model that produced it (`collection_name_for(model_id, dim)` is deterministic).
  An operator can freely switch between models; if a model's collection was
  previously built and docs have not changed, status is `up_to_date` and the
  switch is instantaneous. The collection for the previously-active model remains
  intact. `model_mismatch` therefore means the manifest's recorded dim/model
  does not match the current provider config for that same model — a rare
  corruption state, not the normal model-switch path.
- **Dropdown source is providers configured for the `embeddings` routing purpose.**
  Only providers that have been assigned the `embeddings` purpose in the Routing
  tab appear as choices. This is the same set the Routing tab shows for that row;
  the RAG tab does not introduce a parallel provider list.
- **Button labels and enabled states are fixed by staleness:**
  - *"Update Index"* — triggers `incremental` ingest (re-embeds only changed
    chunks via `content_hash` diff). Disabled when staleness is `missing` or
    `model_mismatch` (no existing collection to diff against).
  - *"Rebuild Index"* — triggers `regenerate` ingest (drops collection, re-embeds
    every document). Always enabled. Required when: model/dimension changed
    (new collection needed), `model_mismatch` (corrupt manifest), or operator
    wants a clean slate. A confirmation prompt guards against accidental use.
  - Neither button is conditionally relabelled; the status pill and banner carry
    the contextual explanation.
- **Qdrant-down is a distinct UI state, not a generic error.** A 503 from
  `GET /api/rag/status` renders an actionable banner: *"Qdrant is not running.
  Start it with `bin/rag up`."* Other backend errors (embeddings config not
  resolved, no provider configured) render their specific message from
  `response.error`. The JS path uses `data.error || data.detail` so FastAPI
  errors and RAG-specific errors are both surfaced rather than collapsed to
  "Request failed."

## Consequences

- **Enables** grounded, cited answers over the project's own docs, lighting up
  the `project_docs` source that the retrieval manifest already advertises.
- **Requires** a running Qdrant container for RAG; the app degrades gracefully
  without it. Operators/devs gain a single `bin/rag` entry point.
- **Requires** the embedding call path to be added to the `"embeddings"`
  routing purpose, and a `qdrant-client` dependency in `gcs_server`.
- **Sequencing.** Slice 1: header-aware chunking + metadata + dense embeddings +
  `search_project_docs` tool + citations. Slice 1.5: hybrid + rerank +
  Contextual Retrieval, and a small **evaluation set** (~10–15 golden
  questions + expected sources, run via `./rag eval`) — gated on explicit
  request, kept as a manual fixture, not a test framework. Later: agentic
  retrieval graph (query rewrite / document grading) and sources #2–#4.
- **`settings_config` stays out of RAG** — small, exact, always-fully-relevant;
  served as structured context / section-scoped tool fetch, not embeddings.
- **`ai_chat_history` scoping (future source, design-only here):** per-operator
  by default, with an optional `share_history` flag for cross-operator
  visibility. Qdrant payload filtering is the enforcement mechanism — a primary
  reason Qdrant was chosen over in-process stores.
- **Supersedes ADR 0007's timing deferral.** ADR 0003's scope is untouched.

## Alternatives Considered

- **In-process store (Chroma / sqlite-vec).** Rejected: preserves the
  single-DB story but weak metadata filtering for per-operator chat-history
  scoping and weaker hybrid support; the multi-source roadmap justifies real
  infrastructure.
- **pgvector.** Rejected: forces a Postgres migration into a SQLite-only repo.
- **Dedicated embedding config block.** Rejected: a parallel config beside the
  existing `"embeddings"` routing purpose; reusing the Provider abstraction
  keeps one source of truth and makes local↔API a config flip.
- **Semantic / pure-LLM chunking for v1.** Rejected: inconsistent benchmark
  gains over structure-aware chunking on already-structured docs, higher cost,
  harder incremental updates. Revisited as optional enrichment, not the base.
- **Full hybrid in slice 1.** Rejected: triples slice-1 failure surface
  (GPU model in-process, sparse queries, RRF tuning) before the basic loop is
  proven. Schema is pre-provisioned so hybrid lands in 1.5 without reindex.
- **Keep deferring (status quo / ADR 0007).** Rejected: a concrete consumer now
  exists, which is exactly the gate ADR 0007 set for revisiting.
