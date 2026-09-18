# 0038. `rover` → `vehicle`: Clean Break On One Wire Key, Four Slices

Tier D renames `rover`-bearing identifiers to `vehicle`. The rename is a large
internal refactor with four narrow external edges, not a broad contract break.
The single client-visible key changes with **no back-compat shim**. The work
ships as four independently verifiable slices inside one PR.

Date: 2026-09-18
Status: Accepted

## Context

[ADR 0037 §Sequencing](./0037-project-naming-and-directory-restructure.md#sequencing--the-governing-rule)
places Tier D before the repository split and requires it to carry its own ADR.
That ADR is this one.

ADR 0037 §Consequences estimated Tier D at "~500 identifiers across the HTTP/WS
contract — larger than the restructure itself", breaking "any client or stored
payload keyed on the old names". That estimate predated any measurement. A
read-only measurement on 2026-09-18 found it wrong in kind, not only in degree:

- 61 distinct `rover`-bearing identifiers, 677 occurrences, 99 files.
- **0 of 113 backend route paths** contain `rover`. No URL changes.
- **No table or column name** contains `rover`. No `ALTER TABLE`.
- **No MQTT topic** contains `rover`, consistent with ADR 0037 leaving MQTT
  contract values unchanged.
- `/api/snapshot` carries no `rover` key.

What remains externally visible is one config/wire key, two stored string values,
two operator-config keys, and seven LLM-facing names. Roughly 80% of the
occurrence count is simulator and frontend internals with no contract at all.

Full evidence, per-file:
[R5 contract surface](../research/2026-09-18-r5-rover-to-vehicle-contract-surface.md).

## Decision

### Blast radius — this ADR supersedes ADR 0037's estimate

The "~500 identifiers across the HTTP/WS contract" bullet in ADR 0037
§Consequences is **superseded by the measurement above**. Tier D is an internal
rename with four narrow edges. Its sequencing placement is unaffected: the
governing rule rests on doing a contract break once rather than twice, and one
break is still a break, so Tier D stays pre-split.

### Clean break on the wire key and the stored replay values

`mqtt.rover_availability` becomes `mqtt.vehicle_availability` on the
device-config endpoint, in both request and response. Its sub-keys
(`connected_threshold_seconds`, `unavailable_threshold_seconds`) are already
vehicle-neutral and do not change.

The two stored replay values change with it: rollover reason `rover_available`
→ `vehicle_available`, and runtime event `rover_became_available` →
`vehicle_became_available`.

**No compatibility alias is written for any of the three.** The server does not
accept or emit the old spellings, and no migration rewrites existing replay rows.

This is safe because the only consumers are in this repository and change in the
same PR: 9 occurrences of the key in `frontend/src`, 6 across `map/` and
`frontend-vanilla/`. The two replay values are **write-only** — nothing in the
tree reads either literal, so historical rows holding them are inert data that no
code branches on.

### Tolerant read for operator config only

Operator config files are the one surface that must not break, because they live
outside the repository on operator machines and no PR updates them. The config
loader reads `mqtt.vehicle_availability` and falls back to
`mqtt.rover_availability` with a warning; likewise intent-parser purpose
`vehicle_intent_parser` falling back to `rover_intent_parser`. This is the
pattern R3 slice 1 established for `active_profile_id` in
`backend/ai/vehicle_profile.py`.

The fallback is a read-side courtesy with a deprecation warning, not a supported
contract. It is removable once the tracked config files are updated.

### `rover_default` keeps its ID

The vehicle-profile ID `rover_default` is **out of scope** and does not change.
It names a rover, which is a real vehicle kind, not a synonym for *vehicle*. It
is the most frequent single literal in the measurement (14 occurrences), so it
will look like an omission to a later pass; it is not. Per
[requirements §Vehicle-bound revisions](../../components/ai-agent/requirements.md)
it is the persisted default and renaming it would break stored missions for no
gain.

### Shape — four slices, one PR

ADR 0037's table says Tier D is one PR; that stands. But it ships as four
slices, each separately verifiable, in this order:

| Slice | Surface | Risk |
|---|---|---|
| 1 | Internal identifiers — `3d-env`, frontend internals | none, mechanical |
| 2 | LLM/Tool Registry names + prompt and eval text | prompt churn |
| 3 | Operator config keys, with the tolerant read above | operator-visible |
| 4 | The wire key + the two stored replay values | the break |

Slices 1–3 are AFK. Slice 4 carries the whole client-visible change and is last
so that everything it depends on is already renamed.

Splitting before dispatch is also the remedy the roadmap's fan-out incident
calls for: an item carrying several boundaries is split first, never executed as
one bundle.

## Consequences

- Any operator running a build from before this PR against a server after it
  loses the availability thresholds on the device-config round trip. Acceptable:
  there are no external clients, and both in-repo frontends move in lockstep.
- Replay sessions recorded before this PR keep `rover_available` /
  `rover_became_available` in `backend/data/gcs_replay.sqlite3`. Both spellings
  will coexist in that file permanently. Nothing reads them, so nothing breaks;
  a future reader that groups by reason must accept both.
- The tolerant config read is the one piece of deliberate back-compat debt from
  this ADR. It carries a deprecation warning and an explicit removal condition.
- `requires_rover_motion` → `requires_vehicle_motion` changes Intent and Mission
  Draft payloads and is hardcoded in prompt text (`backend/ai/prompts.py`), so
  slice 2 must update prompts and re-run evals rather than rename alone.
- ADR 0037 §Consequences' Tier D bullet no longer states the blast radius; this
  ADR does.

## Alternatives Considered

- **Dual-write both spellings on the wire key for one release.** Rejected: there
  is no external client to protect, no release train to stage it across, and the
  alias would outlive its reason. ADR 0036 rejected the same silent-mapping shape
  for simulator backends, and for the same reason — it conceals stale
  configuration.
- **Migrate existing replay rows to the new values.** Rejected: nothing reads
  the literals, so the migration would carry risk against a database of real
  recorded sessions to change data no code consults.
- **Rename `rover_default` too, to finish the job.** Rejected above: it names a
  vehicle kind and is a persisted ID.
- **Four separate PRs.** Rejected: the four surfaces share identifiers, so
  sequential PRs would each rebase on the last with no review benefit. ADR 0037
  already scoped Tier D as one PR.
- **Defer Tier D past the split.** Rejected by ADR 0037's governing rule: a
  change made after the fork must be made twice and diverges.
