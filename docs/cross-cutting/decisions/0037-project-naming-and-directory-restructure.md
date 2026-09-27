# 0037. Project Naming, Directory Convention, And Repository Restructure

The repository is renamed `remote-uxv` and restructured by process boundary
before any public split occurs. Directories are `kebab-case` with one documented
Python exception. `uxv` becomes an organisation, not a name prefix.

Date: 2026-09-06
Status: Accepted
Amended: 2026-09-18 — §Naming scope settles what "no old names in public
history" means (roadmap R4). The original text left it implicit and the
2026-09-07 plan review §7
asked for it to be stated.
Amended: 2026-09-24 — §Sequencing: the restructure, Tier C, and Tier D reach
`master` as one PR (a single fast-forward of `projects-cleanup`), not three.
Operator decision on
review finding 8.
Amended: 2026-09-18 — the Tier D consequence no longer states a blast radius.
[ADR 0038](./0038-rover-to-vehicle-rename.md) owns it and supersedes the
pre-measurement "~500 identifiers across the HTTP/WS contract" estimate.

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
2026-09-06-naming-and-restructure-handoff.md
(archived 2026-09-24 — traceability only; this ADR is the decision truth).

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
| 1 | Restructure stages 0–7 + Tier A `UXV_*` env rename |
| 2 | Tier C vehicle-profile defaulting |
| 3 | Tier D `rover` → `vehicle` + its own ADR |
| PR | Items 1–3 reach `master` together as **one PR**: a single fast-forward of the linear `projects-cleanup` stack |
| then | Split to `uxv-agent` |
| after | Stage 8 — `ai/` → portable `agent_core/` |

Stage 8 is the extraction itself rather than preparation for it, is estimated in
weeks, and is gated on splitting the 2,507-line `tool_registry.py`. It is
therefore not part of that PR, and `agent_core/` does not exist when it lands.

### Naming scope — the tip, not retained history

**Only the published tip must use the new names. Retained history keeps its
original content, unrewritten.** Commits published in `uxv-agent` will contain
`REMOTE_ROVER_*`, `gcs_server/`, and `rover`-keyed identifiers, and that is
accepted. `uxv-agent` is a portfolio artifact
(split handoff Q1); a visible
refactor history demonstrates how the work was done, so rewriting it would
destroy value rather than create it. No historical content rewrite is planned.

This does **not** weaken the sequencing rule above, because that rule rests on
divergence — a change made after the fork must be made twice — not on the
appearance of history. Every item stays pre-split for the reason already given.

The rule is scoped to *content*. Path selection is a separate matter, and
pulls the opposite way: see the extraction-manifest consequence below.

## Consequences

- `pyproject.toml` moves onto the critical path **ahead of the split**. It must
  land before `gcs_server/` → `backend/` rewrites 116 import sites. This delays
  `uxv-agent` extraction by roughly 3–5 days.
- Tier D enters pre-split scope by the sequencing rule and has its own ADR; it
  ships in the same single PR as the restructure. That ADR is
  [ADR 0038](./0038-rover-to-vehicle-rename.md), which owns the blast radius:
  the estimate once given here — "~500 identifiers across the HTTP/WS contract,
  larger than the restructure itself" — was made before measurement and is
  superseded. Tier D is a large internal rename with four narrow external edges;
  no route path, table, column, or MQTT topic changes.
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
- **The extraction manifest must select historical ∪ current paths.** Keeping
  full history (§Naming scope) constrains the `filter-repo` recipe: `--path`
  selection does not follow renames across the commit that performed them, so a
  manifest naming only `backend/`, `rag/`, `tts/`, `frontend-vanilla/`, `map/`
  truncates each file's history at the restructure and makes the public repo
  look as though it began at R1b. The old spellings — `gcs_server/`,
  `rag_service/`, `tts_service/`, `static/` — must be selected alongside the new
  ones. This is the one place the decision to keep history adds work rather than
  removing it.
- Standardizing scene access across the three consumers is **not** done here —
  the directory move is cheap, the contract rework is not. Deferred in
  future-plans.md.

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
  public *tip*, and every commit after the fork, would carry the old names and
  layout permanently, and each rename would then have to be made twice. Read
  forward, not retroactively — per §Naming scope this was never a claim that
  pre-split renames scrub old names from commits that already exist. They do
  not; an ordinary rename commit retains its parents.
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
