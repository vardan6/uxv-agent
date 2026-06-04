"""Behavior-tree mission-content model (ADR 0023, Phase 3).

A Mission's *contents* are a behavior tree, not a flat linear list. ADR 0021
fixed the Mission's identity, origin, UI states, and chat reference resolution
(one sidebar row = one Mission); this module defines the *inside* of that row.

Node taxonomy (ADR 0023 decision 1):

* control flow — ``sequence`` (all children, in order), ``fallback`` (first
  child that succeeds), ``loop`` (repeat a child N times or while a condition
  holds);
* navigation leaf — ``nav_leaf``: an ordered run of waypoints. This is the
  layer that compiles down to a linear MAVLink/``.plan`` mission and runs on the
  flight controller (decision 3); the executor orchestrates the tree around it;
* ``condition`` — a named predicate the executor evaluates;
* ``ask_operator`` — an operator-interaction node ("ask and wait");
* ``recovery`` — a guarded subtree paired with a recovery branch tried when the
  guarded part fails.

Storage format (ADR 0023 Open Question, resolved here): custom JSON, both
human-editable and AI-authored. The serialized form round-trips through
:func:`parse_tree` / :meth:`Node.to_dict`.

Back-compatibility: a pre-0023 flat waypoint list (today's ``mission_json``
payload) is lifted into a single ``sequence`` wrapping one ``nav_leaf`` via
:func:`parse_mission_content`, so existing stored Missions read as trees with no
migration.

This module is self-contained — it imports only stdlib and the coordinate-frame
primitives — so it can relocate onto a companion computer with the executor
(ADR 0023 decision 2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Node type tags as they appear in the serialized JSON ``type`` field.
SEQUENCE = "sequence"
FALLBACK = "fallback"
LOOP = "loop"
NAV_LEAF = "nav_leaf"
CONDITION = "condition"
ASK_OPERATOR = "ask_operator"
RECOVERY = "recovery"

CONTROL_FLOW_TYPES = frozenset({SEQUENCE, FALLBACK, LOOP, RECOVERY})
LEAF_TYPES = frozenset({NAV_LEAF, CONDITION, ASK_OPERATOR})
NODE_TYPES = CONTROL_FLOW_TYPES | LEAF_TYPES

# A ``loop`` runs forever when no positive ``count`` and no ``while_condition``
# are given; the executor relies on this sentinel rather than a magic number.
LOOP_INFINITE = -1


class MissionTreeError(ValueError):
    """Raised when a serialized tree is structurally invalid."""


@dataclass
class Node:
    """One behavior-tree node.

    ``type`` is one of :data:`NODE_TYPES`. The remaining fields are a superset
    across node kinds — only the ones relevant to a given ``type`` are
    populated, mirroring the lightweight JSON the planner and operator author.
    A stable ``id`` lets the executor, overlays, and per-node provenance
    (ADR 0019) address individual nodes.
    """

    type: str
    id: str = ""
    name: str = ""

    # Control-flow children (sequence / fallback / loop / recovery).
    children: list["Node"] = field(default_factory=list)

    # loop: repeat ``count`` times (>=1), or while ``while_condition`` holds, or
    # forever (LOOP_INFINITE). ``count`` and ``while_condition`` are mutually
    # exclusive; validation rejects both at once.
    count: int = LOOP_INFINITE
    while_condition: str = ""

    # nav_leaf: ordered waypoints, each a dict carrying WGS84 truth
    # ({lat, lon, alt}) plus the optional Phase 2 command fields
    # (speed_mps / roi / loiter_time_s). Passed to MissionExportService as-is.
    waypoints: list[dict[str, Any]] = field(default_factory=list)

    # condition / loop.while_condition reference: a named predicate the
    # executor's condition evaluator resolves. ``negate`` flips the result.
    condition: str = ""
    negate: bool = False

    # ask_operator: the operator prompt and how long to wait before the node
    # resolves to ``on_timeout`` ("success" | "failure"). Reuses the
    # confirm-timeout bounds spirit; 0 means wait indefinitely.
    prompt: str = ""
    timeout_s: float = 0.0
    on_timeout: str = "failure"

    def to_dict(self) -> dict[str, Any]:
        """Serialize back to the storage JSON, omitting fields that don't apply
        to this node type so the payload stays minimal and human-readable."""
        data: dict[str, Any] = {"type": self.type}
        if self.id:
            data["id"] = self.id
        if self.name:
            data["name"] = self.name
        if self.type in CONTROL_FLOW_TYPES:
            data["children"] = [child.to_dict() for child in self.children]
        if self.type == LOOP:
            if self.while_condition:
                data["while_condition"] = self.while_condition
            else:
                data["count"] = self.count
        if self.type == NAV_LEAF:
            data["waypoints"] = [dict(wp) for wp in self.waypoints]
        if self.type == CONDITION:
            data["condition"] = self.condition
            if self.negate:
                data["negate"] = True
        if self.type == ASK_OPERATOR:
            data["prompt"] = self.prompt
            data["timeout_s"] = self.timeout_s
            data["on_timeout"] = self.on_timeout
        return data


def parse_tree(data: Any) -> Node:
    """Parse and validate one serialized node (recursively).

    Raises :class:`MissionTreeError` on any structural problem so callers get a
    single, typed failure mode rather than scattered KeyErrors/TypeErrors.
    """
    if not isinstance(data, dict):
        raise MissionTreeError(f"node must be an object, got {type(data).__name__}")

    node_type = str(data.get("type") or "").strip()
    if node_type not in NODE_TYPES:
        raise MissionTreeError(f"unknown node type: {node_type!r}")

    node = Node(
        type=node_type,
        id=str(data.get("id") or ""),
        name=str(data.get("name") or ""),
    )

    if node_type in CONTROL_FLOW_TYPES:
        raw_children = data.get("children")
        if not isinstance(raw_children, list):
            raise MissionTreeError(f"{node_type} node requires a 'children' list")
        node.children = [parse_tree(child) for child in raw_children]

    if node_type == SEQUENCE or node_type == FALLBACK:
        if not node.children:
            raise MissionTreeError(f"{node_type} node must have at least one child")

    if node_type == RECOVERY:
        # A recovery node is a guarded subtree (child 0) plus a recovery branch
        # (child 1) the executor runs only when the guard fails.
        if len(node.children) != 2:
            raise MissionTreeError("recovery node requires exactly two children: [guarded, recovery]")

    if node_type == LOOP:
        if len(node.children) != 1:
            raise MissionTreeError("loop node requires exactly one child")
        while_condition = str(data.get("while_condition") or "").strip()
        has_count = "count" in data
        if while_condition and has_count:
            raise MissionTreeError("loop node cannot set both 'count' and 'while_condition'")
        if while_condition:
            node.while_condition = while_condition
            node.count = LOOP_INFINITE
        elif has_count:
            try:
                count = int(data["count"])
            except (TypeError, ValueError):
                raise MissionTreeError("loop 'count' must be an integer")
            if count < 1:
                raise MissionTreeError("loop 'count' must be >= 1")
            node.count = count
        else:
            node.count = LOOP_INFINITE

    if node_type == NAV_LEAF:
        raw_wps = data.get("waypoints")
        if not isinstance(raw_wps, list) or not raw_wps:
            raise MissionTreeError("nav_leaf node requires a non-empty 'waypoints' list")
        waypoints: list[dict[str, Any]] = []
        for wp in raw_wps:
            if not isinstance(wp, dict):
                raise MissionTreeError("each nav_leaf waypoint must be an object")
            waypoints.append(dict(wp))
        node.waypoints = waypoints

    if node_type == CONDITION:
        condition = str(data.get("condition") or "").strip()
        if not condition:
            raise MissionTreeError("condition node requires a non-empty 'condition'")
        node.condition = condition
        node.negate = bool(data.get("negate", False))

    if node_type == ASK_OPERATOR:
        node.prompt = str(data.get("prompt") or "").strip()
        if not node.prompt:
            raise MissionTreeError("ask_operator node requires a 'prompt'")
        try:
            node.timeout_s = float(data.get("timeout_s") or 0.0)
        except (TypeError, ValueError):
            raise MissionTreeError("ask_operator 'timeout_s' must be a number")
        if node.timeout_s < 0:
            raise MissionTreeError("ask_operator 'timeout_s' must be >= 0")
        on_timeout = str(data.get("on_timeout") or "failure").strip().lower()
        if on_timeout not in ("success", "failure"):
            raise MissionTreeError("ask_operator 'on_timeout' must be 'success' or 'failure'")
        node.on_timeout = on_timeout

    return node


def tree_from_waypoints(waypoints: list[dict[str, Any]]) -> Node:
    """Lift a flat waypoint list into a minimal tree: a sequence wrapping one
    nav_leaf. This is the back-compat bridge for pre-0023 ``mission_json``
    payloads that stored ``{"waypoints": [...]}``."""
    leaf = Node(type=NAV_LEAF, name="waypoints", waypoints=[dict(wp) for wp in waypoints])
    return Node(type=SEQUENCE, name="mission", children=[leaf])


def parse_mission_content(content: Any) -> Node:
    """Parse a stored Mission payload into a behavior tree.

    Accepts both shapes transparently:

    * a tree payload — ``{"tree": {...}}`` or a bare node dict with a ``type``;
    * a legacy flat payload — ``{"waypoints": [...]}`` — lifted via
      :func:`tree_from_waypoints`.

    An empty / contentless payload yields an empty ``sequence`` (a Mission that
    exists but has nothing to run yet), matching ``get_mission_content``'s
    empty-dict sentinel.
    """
    if not isinstance(content, dict):
        raise MissionTreeError("mission content must be an object")

    if isinstance(content.get("tree"), dict):
        return parse_tree(content["tree"])

    if "type" in content:
        return parse_tree(content)

    raw_wps = content.get("waypoints")
    if isinstance(raw_wps, list):
        if not raw_wps:
            return Node(type=SEQUENCE, name="mission", children=[])
        return tree_from_waypoints([wp for wp in raw_wps if isinstance(wp, dict)])

    return Node(type=SEQUENCE, name="mission", children=[])


def flatten_navigable_segments(root: Node) -> list[list[dict[str, Any]]]:
    """Collect the navigable portion of a tree as contiguous waypoint segments.

    ADR 0023 decision 3: only linear navigation runs compile to ``.plan`` and go
    to the FC; the executor orchestrates everything around them. A *segment* is a
    maximal run of waypoints that the FC can execute in one uploaded mission
    without the executor intervening.

    Boundaries: ``nav_leaf`` nodes encountered in execution order within a single
    ``sequence`` chain extend the current segment; any non-nav node
    (condition / ask_operator / fallback / loop / recovery, or a sequence
    boundary that wraps them) closes the current segment, because the executor
    must regain control there. The result is the list of segments in execution
    order, each ready to hand to ``MissionExportService``.
    """
    segments: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []

    def _close() -> None:
        nonlocal current
        if current:
            segments.append(current)
            current = []

    def _walk(node: Node) -> None:
        nonlocal current
        if node.type == NAV_LEAF:
            current.extend(dict(wp) for wp in node.waypoints)
        elif node.type == SEQUENCE:
            # A pure sequence of nav_leaves stays one segment; the first
            # non-nav child closes it and the rest reopen fresh segments.
            for child in node.children:
                _walk(child)
        else:
            # fallback / loop / recovery / condition / ask_operator: the FC
            # cannot represent these, so the executor takes over here.
            _close()

    _walk(root)
    _close()
    return segments
