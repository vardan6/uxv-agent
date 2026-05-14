"""Road graph service for route planning over terrain_scene road network.

Builds an undirected weighted graph from config/terrain_scene.v1.json with:
  - Endpoint snap (configurable epsilon, default 0.5 m)
  - T-junction split pass (mandatory — without it the 16-road scene produces
    4+ disconnected components because connector endpoints hit road interiors)

Provides:
  nearest_node, shortest_path, cover_group, route_to_then_around_then_back
"""

from __future__ import annotations

import heapq
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

_SCENE_PATH = Path(__file__).resolve().parents[2] / "config" / "terrain_scene.v1.json"
_DEFAULT_EPSILON = 0.5
_COST_MULTIPLIERS: dict[str, float] = {
    "preferred": 1.0,
    "default": 1.5,
    "avoid": 1e9,  # treated as impassable
}


def _dist2d(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _point_on_segment(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    """Project p onto segment a-b, return (distance, t) where t ∈ [0,1]."""
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    seg_sq = dx * dx + dy * dy
    if seg_sq < 1e-12:
        return _dist2d(p, a), 0.0
    t = ((px - ax) * dx + (py - ay) * dy) / seg_sq
    tc = max(0.0, min(1.0, t))
    cx, cy = ax + tc * dx, ay + tc * dy
    return _dist2d(p, (cx, cy)), tc


def _lerp_z(az: float, bz: float, t: float) -> float:
    return az + (bz - az) * t


class RoadGraphService:
    """Undirected weighted road graph over terrain_scene roads.

    On startup call build() (or let __init__ call it automatically).
    After build, node_count and edge_count reflect the split graph.
    """

    def __init__(self, scene_path: str | Path | None = None, epsilon: float = _DEFAULT_EPSILON):
        self._scene_path = Path(scene_path) if scene_path else _SCENE_PATH
        self._epsilon = epsilon
        # node_id -> (x, y, z)
        self._nodes: list[tuple[float, float, float]] = []
        # list of (node_a, node_b, weight, edge_id, group, width)
        self._edges: list[tuple[int, int, float, str, str, float]] = []
        # adjacency list: node_id -> [(neighbour_id, weight, edge_idx)]
        self._adj: dict[int, list[tuple[int, float, int]]] = defaultdict(list)
        self.build()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    def nearest_node(self, x: float, y: float) -> int:
        """Return the node id closest to (x, y)."""
        if not self._nodes:
            raise RuntimeError("graph has no nodes")
        best_d = math.inf
        best_i = 0
        for i, (nx, ny, _) in enumerate(self._nodes):
            d = _dist2d((x, y), (nx, ny))
            if d < best_d:
                best_d = d
                best_i = i
        return best_i

    def shortest_path(self, start: int, goal: int) -> list[int]:
        """Dijkstra from start to goal node; returns ordered node list."""
        if start == goal:
            return [start]
        dist_: dict[int, float] = {start: 0.0}
        prev: dict[int, int | None] = {start: None}
        pq: list[tuple[float, int]] = [(0.0, start)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist_.get(u, math.inf):
                continue
            if u == goal:
                break
            for v, w, _ in self._adj.get(u, []):
                nd = d + w
                if nd < dist_.get(v, math.inf):
                    dist_[v] = nd
                    prev[v] = u
                    heapq.heappush(pq, (nd, v))
        if goal not in prev and goal != start:
            return []
        path: list[int] = []
        cur: int | None = goal
        while cur is not None:
            path.append(cur)
            cur = prev.get(cur)
        path.reverse()
        return path if path[0] == start else []

    def path_waypoints(self, node_path: list[int]) -> list[dict[str, float]]:
        """Convert a node-id path to a list of {x, y, z} waypoints."""
        return [
            {"x": self._nodes[n][0], "y": self._nodes[n][1], "z": self._nodes[n][2]}
            for n in node_path
        ]

    def path_length_m(self, node_path: list[int]) -> float:
        total = 0.0
        for i in range(len(node_path) - 1):
            a = self._nodes[node_path[i]]
            b = self._nodes[node_path[i + 1]]
            total += _dist2d((a[0], a[1]), (b[0], b[1]))
        return total

    def cover_group(self, group: str, entry_node: int) -> list[int]:
        """Return a node-ordered tour visiting every edge in `group` ≥ once,
        starting and ending at entry_node. Uses Chinese-Postman for odd-degree nodes."""
        group_edge_indices = [
            i for i, (_, _, _, _, g, _) in enumerate(self._edges) if g == group
        ]
        if not group_edge_indices:
            return [entry_node]

        # Build subgraph node set and adjacency
        sub_nodes: set[int] = set()
        sub_adj: dict[int, list[tuple[int, float, int]]] = defaultdict(list)
        for ei in group_edge_indices:
            a, b, w, _, _, _ = self._edges[ei]
            sub_nodes.add(a)
            sub_nodes.add(b)
            sub_adj[a].append((b, w, ei))
            sub_adj[b].append((a, w, ei))

        if entry_node not in sub_nodes:
            # Snap entry_node to the nearest subgraph node
            entry_node = min(
                sub_nodes,
                key=lambda n: self._graph_distance(entry_node, n),
            )

        # Find odd-degree nodes
        degree: dict[int, int] = defaultdict(int)
        for n in sub_nodes:
            degree[n] = len(sub_adj[n])
        odd_nodes = [n for n in sub_nodes if degree[n] % 2 != 0]

        # Pair up odd nodes and duplicate shortest paths (Chinese-Postman)
        extra_edges: list[tuple[int, int, float, str, str, float]] = []
        unpaired = list(odd_nodes)
        while len(unpaired) >= 2:
            # Greedy nearest-pair matching — sufficient for ≤ ~8 odd nodes
            best_pair: tuple[int, int] | None = None
            best_d = math.inf
            for i in range(len(unpaired)):
                for j in range(i + 1, len(unpaired)):
                    d = self._graph_distance(unpaired[i], unpaired[j])
                    if d < best_d:
                        best_d = d
                        best_pair = (unpaired[i], unpaired[j])
            if best_pair is None:
                break
            u, v = best_pair
            path = self.shortest_path(u, v)
            for k in range(len(path) - 1):
                a, b = path[k], path[k + 1]
                w = _dist2d(
                    (self._nodes[a][0], self._nodes[a][1]),
                    (self._nodes[b][0], self._nodes[b][1]),
                )
                extra_edges.append((a, b, w, f"dup_{a}_{b}", group, 0.0))
                sub_adj[a].append((b, w, len(self._edges) + len(extra_edges) - 1))
                sub_adj[b].append((a, w, len(self._edges) + len(extra_edges) - 1))
            unpaired = [n for n in unpaired if n not in best_pair]

        # Hierholzer Eulerian circuit from entry_node
        circuit = self._eulerian_circuit(entry_node, sub_adj)
        return circuit

    def route_to_then_around_then_back(
        self, start_x: float, start_y: float, group: str
    ) -> dict[str, Any]:
        """Compose: transit to group entry → cover all group edges → return to start.

        Returns a route summary dict with waypoints and leg breakdown.
        """
        start_node = self.nearest_node(start_x, start_y)

        # Find entry node: group node closest by graph distance to start
        group_nodes = {
            n
            for i, (a, b, _, _, g, _) in enumerate(self._edges)
            if g == group
            for n in (a, b)
        }
        if not group_nodes:
            return {"ok": False, "error": f"group '{group}' has no edges"}

        entry_node = min(group_nodes, key=lambda n: self._graph_distance(start_node, n))

        transit_in = self.shortest_path(start_node, entry_node)
        cover = self.cover_group(group, entry_node)
        transit_out = self.shortest_path(entry_node, start_node)

        # Stitch: avoid duplicate junction nodes at seams
        full_path = transit_in + cover[1:] + transit_out[1:]

        waypoints = self.path_waypoints(full_path)
        transit_in_dist = self.path_length_m(transit_in)
        cover_dist = self.path_length_m(cover)
        transit_out_dist = self.path_length_m(transit_out)
        total_dist = transit_in_dist + cover_dist + transit_out_dist

        return {
            "ok": True,
            "group": group,
            "waypoint_count": len(waypoints),
            "total_distance_m": round(total_dist, 2),
            "legs": [
                {"name": "transit_to_group", "distance_m": round(transit_in_dist, 2), "node_count": len(transit_in)},
                {"name": "cover_group", "distance_m": round(cover_dist, 2), "node_count": len(cover)},
                {"name": "return_to_start", "distance_m": round(transit_out_dist, 2), "node_count": len(transit_out)},
            ],
            "waypoints": waypoints,
            "start_node": start_node,
            "entry_node": entry_node,
        }

    def route_between(
        self,
        start_x: float,
        start_y: float,
        goal_x: float,
        goal_y: float,
    ) -> dict[str, Any]:
        """Dijkstra route from start to goal world coordinates."""
        start_node = self.nearest_node(start_x, start_y)
        goal_node = self.nearest_node(goal_x, goal_y)
        path = self.shortest_path(start_node, goal_node)
        if not path:
            return {"ok": False, "error": "no path found between start and goal"}
        waypoints = self.path_waypoints(path)
        total_dist = self.path_length_m(path)
        return {
            "ok": True,
            "waypoint_count": len(waypoints),
            "total_distance_m": round(total_dist, 2),
            "waypoints": waypoints,
            "start_node": start_node,
            "goal_node": goal_node,
        }

    def known_groups(self) -> list[str]:
        return sorted({g for _, _, _, _, g, _ in self._edges if g})

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def build(self) -> None:
        raw_roads = self._load_roads()
        segments = self._split_at_t_junctions(raw_roads)
        self._nodes = []
        self._edges = []
        self._adj = defaultdict(list)

        node_map: dict[int, int] = {}  # segment endpoint index -> node id

        def find_or_add(x: float, y: float, z: float) -> int:
            for i, (nx, ny, _) in enumerate(self._nodes):
                if _dist2d((x, y), (nx, ny)) <= self._epsilon:
                    return i
            self._nodes.append((x, y, z))
            return len(self._nodes) - 1

        for seg_id, (ax, ay, az), (bx, by, bz), width, cost_mult, group in segments:
            na = find_or_add(ax, ay, az)
            nb = find_or_add(bx, by, bz)
            if na == nb:
                continue
            w = _dist2d((ax, ay), (bx, by)) * cost_mult
            ei = len(self._edges)
            self._edges.append((na, nb, w, seg_id, group, width))
            self._adj[na].append((nb, w, ei))
            self._adj[nb].append((na, w, ei))

    def _load_roads(self) -> list[dict[str, Any]]:
        scene = json.loads(self._scene_path.read_text())
        roads = []
        for r in scene.get("roads", []):
            if not r.get("metadata", {}).get("drivable", True):
                continue
            cost_key = str(r.get("metadata", {}).get("route_planning_cost", "default"))
            roads.append({
                "id": r["id"],
                "a": tuple(float(v) for v in r["centerline"][0]),
                "b": tuple(float(v) for v in r["centerline"][1]),
                "width": float(r.get("geometry", {}).get("width", 4.0)),
                "cost_mult": _COST_MULTIPLIERS.get(cost_key, 1.5),
                "group": str(r.get("metadata", {}).get("group", "")),
            })
        return roads

    def _split_at_t_junctions(
        self, roads: list[dict[str, Any]]
    ) -> list[tuple[str, tuple, tuple, float, float, str]]:
        """For each road, find other-road endpoints that land on its interior;
        split there. Returns list of (id, a_xyz, b_xyz, width, cost_mult, group)."""
        segments: list[tuple[str, tuple, tuple, float, float, str]] = []

        for road in roads:
            rid = road["id"]
            ax, ay, az = road["a"]
            bx, by, bz = road["b"]
            width = road["width"]
            cost_mult = road["cost_mult"]
            group = road["group"]

            # Collect interior split points from other roads' endpoints
            split_ts: list[float] = []
            for other in roads:
                if other["id"] == rid:
                    continue
                for ep, ez in ((other["a"][:2], other["a"][2]), (other["b"][:2], other["b"][2])):
                    d, t = _point_on_segment(ep, (ax, ay), (bx, by))
                    if d <= self._epsilon and 0.05 < t < 0.95:
                        split_ts.append(t)

            if not split_ts:
                segments.append((rid, (ax, ay, az), (bx, by, bz), width, cost_mult, group))
                continue

            # Sort unique t values and emit sub-segments
            split_ts_sorted = sorted(set(round(t, 6) for t in split_ts))
            all_ts = [0.0] + split_ts_sorted + [1.0]
            for k in range(len(all_ts) - 1):
                t0, t1 = all_ts[k], all_ts[k + 1]
                xa = ax + (bx - ax) * t0
                ya = ay + (by - ay) * t0
                za = _lerp_z(az, bz, t0)
                xb = ax + (bx - ax) * t1
                yb = ay + (by - ay) * t1
                zb = _lerp_z(az, bz, t1)
                seg_id = f"{rid}_s{k}" if len(all_ts) > 2 else rid
                segments.append((seg_id, (xa, ya, za), (xb, yb, zb), width, cost_mult, group))

        return segments

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _graph_distance(self, start: int, goal: int) -> float:
        if start == goal:
            return 0.0
        dist_: dict[int, float] = {start: 0.0}
        pq: list[tuple[float, int]] = [(0.0, start)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == goal:
                return d
            if d > dist_.get(u, math.inf):
                continue
            for v, w, _ in self._adj.get(u, []):
                nd = d + w
                if nd < dist_.get(v, math.inf):
                    dist_[v] = nd
                    heapq.heappush(pq, (nd, v))
        return math.inf

    def _eulerian_circuit(
        self, start: int, adj: dict[int, list[tuple[int, float, int]]]
    ) -> list[int]:
        """Hierholzer's algorithm for Eulerian circuit starting at `start`.
        Modifies a local copy of adjacency lists."""
        local_adj: dict[int, list[tuple[int, float, int]]] = {
            n: list(neighbours) for n, neighbours in adj.items()
        }
        used_edges: set[int] = set()
        stack = [start]
        circuit: list[int] = []

        while stack:
            v = stack[-1]
            moved = False
            while local_adj.get(v):
                neighbour, w, ei = local_adj[v].pop()
                if ei in used_edges:
                    continue
                used_edges.add(ei)
                # Remove the reverse edge too
                rev = local_adj.get(neighbour, [])
                for k, (nb2, w2, ei2) in enumerate(rev):
                    if ei2 == ei:
                        rev.pop(k)
                        break
                stack.append(neighbour)
                moved = True
                break
            if not moved:
                circuit.append(stack.pop())

        circuit.reverse()
        return circuit
