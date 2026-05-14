"""PROTOTYPE — throwaway diagnostic for RoadGraphService design.

Question this answers:
  1. What endpoint-snap epsilon is appropriate for terrain_scene.v1.json?
  2. Are T-junctions / mid-segment intersections actually present in the scene
     (i.e. is the "split at interior point" pass really necessary)?
  3. At the chosen epsilon, is the graph one connected component?

How to run (from repo root):
    python gcs_server/ai/_prototype_road_graph.py

Wipe me once the verdict is captured in _prototype_road_graph_NOTES.md.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCENE_PATH = REPO_ROOT / "config" / "terrain_scene.v1.json"

CANDIDATE_EPSILONS = [0.1, 0.5, 1.0, 2.0]


def load_roads():
    scene = json.loads(SCENE_PATH.read_text())
    roads = []
    for r in scene["roads"]:
        a, b = r["centerline"][0], r["centerline"][1]
        roads.append(
            {
                "id": r["id"],
                "a": (float(a[0]), float(a[1])),
                "b": (float(b[0]), float(b[1])),
                "az": float(a[2]),
                "bz": float(b[2]),
                "width": r["geometry"]["width"],
                "cost": r["metadata"].get("route_planning_cost", "default"),
            }
        )
    return roads


def dist(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


def point_to_segment_distance(p, a, b):
    """Distance from point p to segment a-b. Returns (distance, t) where t in [0,1] is the projection."""
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq < 1e-12:
        return dist(p, a), 0.0
    t = ((px - ax) * dx + (py - ay) * dy) / seg_len_sq
    t_clamped = max(0.0, min(1.0, t))
    closest = (ax + t_clamped * dx, ay + t_clamped * dy)
    return dist(p, closest), t_clamped


def analyse_endpoints(roads):
    print("=" * 72)
    print("§1  ENDPOINT NEAREST-NEIGHBOUR DISTANCES")
    print("=" * 72)
    endpoints = []
    for r in roads:
        endpoints.append((r["id"] + ":a", r["a"]))
        endpoints.append((r["id"] + ":b", r["b"]))

    nn = []
    for i, (lbl_i, p_i) in enumerate(endpoints):
        best = (math.inf, None)
        for j, (lbl_j, p_j) in enumerate(endpoints):
            if i == j:
                continue
            d = dist(p_i, p_j)
            if d < best[0]:
                best = (d, lbl_j)
        nn.append((lbl_i, best[0], best[1]))

    # Distance histogram
    buckets = [0, 0, 0, 0, 0, 0]
    labels = ["= 0.0", "0 < d ≤ 0.1", "0.1 < d ≤ 0.5", "0.5 < d ≤ 1.0", "1.0 < d ≤ 5.0", "> 5.0"]
    for _, d, _ in nn:
        if d == 0.0:
            buckets[0] += 1
        elif d <= 0.1:
            buckets[1] += 1
        elif d <= 0.5:
            buckets[2] += 1
        elif d <= 1.0:
            buckets[3] += 1
        elif d <= 5.0:
            buckets[4] += 1
        else:
            buckets[5] += 1

    print(f"  {len(endpoints)} endpoints from {len(roads)} roads")
    print("  Nearest-neighbour distance histogram:")
    for lbl, cnt in zip(labels, buckets):
        print(f"    {lbl:>15}  {cnt:>3}  {'█' * cnt}")

    # Print every endpoint with its nearest neighbour, sorted by distance
    print("\n  Per-endpoint nearest neighbour (sorted, top 12 + bottom 4):")
    nn_sorted = sorted(nn, key=lambda x: x[1])
    for row in nn_sorted[:12]:
        print(f"    {row[0]:<40} → {row[2]:<40}  d = {row[1]:.4f}")
    if len(nn_sorted) > 16:
        print("    ...")
    for row in nn_sorted[-4:]:
        print(f"    {row[0]:<40} → {row[2]:<40}  d = {row[1]:.4f}")


def analyse_t_junctions(roads, eps):
    print()
    print("=" * 72)
    print(f"§2  T-JUNCTIONS / MID-SEGMENT INTERSECTIONS (epsilon={eps} m)")
    print("=" * 72)
    findings = []
    for r in roads:
        for other in roads:
            if other["id"] == r["id"]:
                continue
            for which, ep in (("a", other["a"]), ("b", other["b"])):
                d, t = point_to_segment_distance(ep, r["a"], r["b"])
                # Only count it as mid-segment if t is meaningfully interior
                if d <= eps and 0.05 < t < 0.95:
                    findings.append(
                        f"  {other['id']}:{which} hits interior of {r['id']} (t={t:.3f}, d={d:.4f} m)"
                    )
    if not findings:
        print("  No mid-segment intersections detected. Endpoint-only merge is sufficient.")
    else:
        print(f"  {len(findings)} mid-segment hits found — T-junction split logic IS required.")
        for line in findings:
            print(line)
    return len(findings)


def build_graph(roads, eps):
    """Endpoint-snap only; no T-junction split. Used to test connectivity at varying epsilons."""
    nodes = []  # list of representative (x,y) points

    def find_or_add(p):
        for i, n in enumerate(nodes):
            if dist(p, n) <= eps:
                return i
        nodes.append(p)
        return len(nodes) - 1

    edges = []
    for r in roads:
        a = find_or_add(r["a"])
        b = find_or_add(r["b"])
        if a != b:
            edges.append((a, b, r["id"]))

    # union-find
    parent = list(range(len(nodes)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, _ in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    components = len({find(i) for i in range(len(nodes))})
    return len(nodes), len(edges), components


def analyse_connectivity(roads):
    print()
    print("=" * 72)
    print("§3  GRAPH CONNECTIVITY AT CANDIDATE EPSILONS (endpoint-snap only)")
    print("=" * 72)
    print(f"  {'epsilon (m)':>12}  {'nodes':>6}  {'edges':>6}  {'components':>11}")
    for eps in CANDIDATE_EPSILONS:
        n, e, c = build_graph(roads, eps)
        marker = "  ← single component" if c == 1 else f"  ← {c} components, GRAPH DISCONNECTED"
        print(f"  {eps:>12.2f}  {n:>6}  {e:>6}  {c:>11}{marker}")


def main():
    roads = load_roads()
    print(f"Loaded {len(roads)} roads from {SCENE_PATH.relative_to(REPO_ROOT)}\n")
    for r in roads:
        print(f"  {r['id']:<32}  a={r['a']}  b={r['b']}  width={r['width']}  cost={r['cost']}")
    print()

    analyse_endpoints(roads)

    for eps in (0.5, 1.0):
        analyse_t_junctions(roads, eps)

    analyse_connectivity(roads)


if __name__ == "__main__":
    main()
