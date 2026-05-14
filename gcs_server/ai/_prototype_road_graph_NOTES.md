# Prototype verdict — RoadGraphService design

**Date:** 2026-05-15
**Prototype:** `_prototype_road_graph.py`
**Run with:** `python3 gcs_server/ai/_prototype_road_graph.py`

## Questions and answers

### Q1. What endpoint-snap epsilon is right?

**Answer: any small value works; 0.5 m default is safe.**

- The scene was authored with **canonical shared coordinates**: 27 of 32 endpoints have a nearest-neighbour distance of *exactly* 0.0. The remaining 5 endpoints are connector starts/ends that T-junction into loop interiors (also exact, but not endpoint-to-endpoint).
- Distance histogram has a hard gap: bucket "= 0.0" holds 27 entries; bucket "0 < d ≤ 5.0" holds 0; bucket "> 5.0" holds 5.
- There are **no near-misses** in the 0.1–5 m range. Any epsilon between 0.0 (exclusive) and ~26 m would behave identically on the *current* scene.
- Recommendation: keep the 0.5 m default and the Settings-tunable knob from the design doc. It's not load-bearing on this scene but will matter once scene authoring stops producing exact coordinates (real-world data, third-party exporter, hand edits).

### Q2. Are T-junctions / mid-segment intersections actually present?

**Answer: yes — 4 of them — and the split pass is mandatory.**

Mid-segment hits found at t = 0.5 (exact midpoints):

| Connector endpoint                | Hits interior of      |
| --------------------------------- | --------------------- |
| `road_building_to_plant_a_1:b`    | `road_plant_a_loop_1` |
| `road_plants_connector_0:a`       | `road_plant_a_loop_2` |
| `road_plants_connector_1:b`       | `road_plant_b_loop_0` |
| `road_building_to_plant_b_1:b`    | `road_plant_b_loop_3` |

Each loop is "entered" by a connector that tees into the *middle* of one of its edges, not at a corner.

### Q3. Is the graph connected with endpoint-only merge?

**Answer: no — 4 disconnected components at every candidate epsilon.**

```
epsilon (m)   nodes   edges   components
       0.10      18      16            4  ← DISCONNECTED
       0.50      18      16            4  ← DISCONNECTED
       1.00      18      16            4  ← DISCONNECTED
       2.00      18      16            4  ← DISCONNECTED
```

Without the T-junction split, the planner cannot route plant-a → plant-b at all: the plant_a loop, plant_b loop, the building-to-plant trunks + connectors, and the start hub are four separate islands. The split pass is what makes routing work.

## Implications for the implementation

1. **Keep the configurable `road_graph_epsilon_m` Setting** (default 0.5). Validated as the right shape even though it's not load-bearing on the current scene.
2. **The T-junction split pass is required, not optional.** Drop it and the system silently produces an unroutable graph. Add a startup assertion in `RoadGraphService` that the post-split graph has exactly one connected component, and fail loudly if not — this is the single cheapest regression guard.
3. **Naive O(n²) split is fine.** With 16 edges and 32 endpoints the whole analysis runs in milliseconds.
4. **No need to design for "approximate shared coordinates" yet.** Authoring is exact today; revisit if a future scene loses that property.

## Next steps

- Fold these findings into the `RoadGraphService` implementation (PR slice).
- Delete this prototype directory once `RoadGraphService` ships: `_prototype_road_graph.py` and this NOTES file.
