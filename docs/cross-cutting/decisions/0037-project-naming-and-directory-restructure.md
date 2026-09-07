# 0037. Project Naming, Directory Convention, And Repository Restructure

The repository is renamed `remote-uxv` and restructured by process boundary
before any public split occurs. Directories are `kebab-case` with one documented
Python exception. `uxv` becomes an organisation, not a name prefix.

Date: 2026-09-06
Status: Accepted

## Context

The root project name was never actually chosen. `uxv-gcs` circulated as a
working answer but was never ratified, and the operator has now rejected it: the
root holds subprojects with independent futures, so naming it after one of them
undersells the tree. `remote-rover` is factually wrong for a project that now
covers a multirotor.

Two prior planning sessions produced a target tree, a naming inventory, and a
staged migration plan, but left them explicitly unratified — a draft ADR was
written and deliberately not adopted. A grilling session on 2026-09-06 closed
the remaining questions. Full working record, including measurements and
rejected candidates, is in
[handoff-naming-and-restructure-2026-09-06.md](../handoff-naming-and-restructure-2026-09-06.md).

Measurements that drove these decisions, verified and not to be re-derived:

- **No `pyproject.toml`, `setup.py`, or `setup.cfg` exists.** 116
  `from gcs_server.…` statements resolve only because the repo root is on
  `sys.path` (`bin/rag:33`). No Python package can be nested deeper without
  packaging config first.
- `scene` appears **691 times across 41 code files**; `terrain` 225; `world`
  **25**. The existing vocabulary is *scene*.
- `3d-env` appears **302 times** in tracked files, including as the config and
  wire value `"backend": "3d-env"`.
- `mav_sim` has **zero package-level import sites**; `mav-sim/run.sh:17`
  launches it by path (`cd "$DIR" && exec python app.py`), not `python -m`.
- `road_graph_service.py` has exactly three referents: `ai/tool_registry.py`,
  its own test, and `scene/pipeline/sync_terrain_scene.sh`.

## Decision

### Names

| Thing | Name |
|---|---|
| Root repository and local directory | **`remote-uxv`** (was `remote-rover`) |
| Public extracted agent repository | **`uxv-agent`** — unchanged, settled 2026-09-02 |
| Backend | **`backend/`** (was `gcs_server/`) |
| World data + pipeline | **`scene/`** |
| RAG service | **`rag/`** · TTS service **`tts/`** |
| Simulators | **`mav-sim/`** and **`3d-env/`** — two independent siblings |
| Frontends | **`frontend/`** (React) and **`frontend-vanilla/`** |
| Map widget package | **`map/`** |
| Portable agent core | **`agent_core/`** |
| Environment variables | **`UXV_*`** (was `REMOTE_ROVER_*`) |

`uxv` is an **organisation**, not a name prefix. Repositories take short
functional names underneath it. `uxv-sim` is abandoned — the two simulators have
independent open-source futures and do not share a name.

### Directory convention

All directories are `kebab-case`, with one exception: a directory Python imports
must be a valid identifier, so those stay single-word, and a genuinely necessary
multi-word Python package takes an underscore. Currently invoked once:
`agent_core/`. The convention is canonical in
[STYLE.md §Repository Directory And File Naming](../../STYLE.md#repository-directory-and-file-naming).

### Structure

Directories divide by **process boundary and lifecycle**, not topic: `backend`
is one process; `rag` and `tts` are separate processes; `map` is a package that
leaves the repo; `scene` is data plus its pipeline; the simulators never ship to
production but are independent OSS candidates.

`scene_map.py` moves into `scene/` — it is the backend reader for the agent
tools and map widget, and has zero FastAPI imports. The 3D env is a separate
consumer: `3d-env/simulator/terrain.py` opens the manifest directly. The move
therefore updates both readers, plus the independent path logic in the terrain
generation and validation tools; it does not standardize their access contract.
`road_graph_service.py` **stays in `ai/`**: routing is agent behaviour, and the
graph is derived from the scene *for one consumer*.

`static/` **dissolves** into `frontend-vanilla/` and `map/`. Nothing is deleted;
parity-triggered deletion remains a later decision inside `frontend-vanilla/`.

`tools/` and root `bin/` dissolve into their owners. `xx` and `.vite/` are
deleted. `ArduPilot-SITL` remains as a local-development symlink to the sibling
clone because it is needed for future simulator work; it is not part of the
restructure cleanup.

### Sequencing — the governing rule

**Every change that will enter both the private and the public repository lands
before the split.** Refactor, clean up, verify it works, then fork. A change
made after the fork must be made twice and diverges.

| Order | Work |
|---|---|
| PR 1 | Restructure stages 0–7 + Tier A `UXV_*` env rename |
| PR 2 | Tier C vehicle-profile defaulting |
| PR 3 | Tier D `rover` → `vehicle` + its own ADR |
| then | Split to `uxv-agent` |
| after | Stage 8 — `ai/` → portable `agent_core/` |

Stage 8 is the extraction itself rather than preparation for it, is estimated in
weeks, and is gated on splitting the 2,507-line `tool_registry.py`. It is
therefore not part of PR 1 and `agent_core/` does not exist when PR 1 lands.

## Consequences

- `pyproject.toml` moves onto the critical path **ahead of the split**. It must
  land before `gcs_server/` → `backend/` rewrites 116 import sites. This delays
  `uxv-agent` extraction by roughly 3–5 days.
- Tier D enters pre-split scope by the sequencing rule. It is ~500 identifiers
  across the HTTP/WS contract — larger than the restructure itself — and breaks
  any client or stored payload keyed on the old names. It ships as its own PR
  with its own ADR rather than inside PR 1.
- `uxv-agent` was settled 2026-09-02 as the *public repository* name. It stays
  there; it is not reassigned to the root.
- The local absolute path changes from `~/Proj/remote-rover` to
  `~/Proj/remote-uxv`. The `ArduPilot-SITL` symlink targets a sibling directory
  and remains a local-development integration pointer.
- `3d-env` is a wire and config value, not merely a path. The directory name
  stays hyphenated so directory and contract agree. Renaming it would collide
  with [ADR 0036](./0036-retire-rover-sim-next.md), which made unsupported
  backend values fail validation rather than fall back.
- The `mav_sim` **gRPC proto package** (`proto/mav_sim.proto`,
  `mav_sim.MavSim/*`) is a wire identifier and is **not** renamed with the
  directory.
- `map/sources/world/` retains the word *world*, where it contrasts against
  *authored*. That is a real distinction, not a synonym for `scene/`.
- Standardizing scene access across the three consumers is **not** done here —
  the directory move is cheap, the contract rework is not. Deferred in
  [future-plans.md](../../future-plans.md).

## Alternatives Considered

- **`world/` for the scene directory, renaming the vocabulary to match.** The
  earlier recommendation. Rejected on measurement: 691 `scene` occurrences
  against 25 for `world`, and the name is on the wire (`/api/replay/scene-map`),
  on disk (`terrain_scene.v1.json`), and in the map widget
  (`SceneObjectsLayer`). A Tier-D-sized rename wearing a stage-2 costume.
- **`uxv-agent` as the root name**, with `uxv-agent-lite` or `-public` for the
  split. Rejected: it reassigns the one settled subproject name; it repeats the
  objection that killed `uxv-gcs`, since the root also holds the backend, two
  frontends, the map, the scene pipeline, RAG, TTS, and two simulators; and the
  derived names undersell the public repository, which is the one with an
  audience.
- **Split first, restructure after.** Rejected by the sequencing rule: the
  public history would carry the old names and layout permanently.
- **Hybrid — stages 0–3 before the split, 4–8 after.** Rejected for the same
  reason, though it remains the cheaper option if sequencing is ever revisited.
  `git filter-repo --path-rename` stays available as the fallback.
- **`mavsim/`, `3denv/`, `env3d/`.** Rejected: `mav-sim` and `3d-env` already
  satisfy kebab-case, so squashed compounds would be the deviation. Neither is
  Python-imported, and `3denv` could not be an identifier anyway because it
  starts with a digit — the rename buys nothing and desyncs 302 wire values.
- **`snake_case` everywhere**, or **kebab for non-Python and snake for Python**.
  Both rejected: the first looks dated in the JS half and still cannot rescue
  `3d_env`; the second is per-language mixing of visual style, which the
  operator explicitly ruled out.
- **`agentkit`** as a single-word portable-core name avoiding the underscore
  exception. Rejected on collision — OpenAI and Inngest both ship an "AgentKit".
- **Stage-per-PR delivery.** Rejected by the operator in favour of one
  reviewable restructure PR.
