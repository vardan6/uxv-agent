from __future__ import annotations

from ai import polygon_geometry as g

UNIT_SQUARE: list[g.Point] = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


def test_signed_area_and_degeneracy() -> None:
    assert abs(g.signed_area(UNIT_SQUARE)) == 1.0
    assert not g.is_degenerate(UNIT_SQUARE)
    # Fewer than three vertices, or all-collinear, is degenerate (zero area).
    assert g.is_degenerate([(0.0, 0.0), (1.0, 0.0)])
    assert g.is_degenerate([(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)])


def test_self_intersection() -> None:
    assert not g.self_intersects(UNIT_SQUARE)
    # Classic bow-tie: edges (0,0)->(1,1) and (1,0)->(0,1) cross.
    assert g.self_intersects([(0.0, 0.0), (1.0, 1.0), (1.0, 0.0), (0.0, 1.0)])


def test_point_in_ring() -> None:
    assert g.point_in_ring((0.5, 0.5), UNIT_SQUARE)
    assert not g.point_in_ring((2.0, 2.0), UNIT_SQUARE)


def test_segment_enters_polygon_with_outside_endpoints() -> None:
    # Both endpoints are outside the square but the leg cuts straight through it.
    assert g.segment_enters_polygon((-1.0, 0.5), (2.0, 0.5), UNIT_SQUARE)
    # A leg that stays clear of the square does not enter it.
    assert not g.segment_enters_polygon((-1.0, 2.0), (2.0, 2.0), UNIT_SQUARE)
    # A leg fully inside the square enters it.
    assert g.segment_enters_polygon((0.2, 0.5), (0.8, 0.5), UNIT_SQUARE)


def test_segment_within_single_corridor() -> None:
    assert g.segment_within_union((0.2, 0.5), (0.8, 0.5), [UNIT_SQUARE])
    # Leaves the square partway along the leg.
    assert not g.segment_within_union((0.5, 0.5), (1.5, 0.5), [UNIT_SQUARE])


def test_segment_within_union_of_adjacent_corridors() -> None:
    # Two squares sharing the x=1 edge cover [0,2]x[0,1] with no gap.
    right = [(1.0, 0.0), (2.0, 0.0), (2.0, 1.0), (1.0, 1.0)]
    assert g.segment_within_union((0.5, 0.5), (1.5, 0.5), [UNIT_SQUARE, right])
    # A gap between two separated corridors is detected.
    far = [(3.0, 0.0), (4.0, 0.0), (4.0, 1.0), (3.0, 1.0)]
    assert not g.segment_within_union((0.5, 0.5), (3.5, 0.5), [UNIT_SQUARE, far])
