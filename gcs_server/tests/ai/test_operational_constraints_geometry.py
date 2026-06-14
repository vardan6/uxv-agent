from __future__ import annotations

import pytest

from ai.operational_constraints_store import (
    ConstraintValidationError,
    OperationalConstraintsStore,
    _normalize_polygon,
)

VALID_SQUARE = [
    {"lat": 0.0, "lon": 0.0},
    {"lat": 0.0, "lon": 1.0},
    {"lat": 1.0, "lon": 1.0},
    {"lat": 1.0, "lon": 0.0},
]


def test_accepts_open_square() -> None:
    out = _normalize_polygon(VALID_SQUARE)
    assert len(out) == 4


def test_normalizes_redundant_closing_vertex() -> None:
    # A client that repeats the first vertex to "close" the ring gets it stripped,
    # not stored as a fourth/fifth vertex.
    closed = VALID_SQUARE + [{"lat": 0.0, "lon": 0.0}]
    assert len(_normalize_polygon(closed)) == 4


def test_rejects_non_finite_vertices() -> None:
    for bad in (float("nan"), float("inf"), float("-inf")):
        poly = [{"lat": bad, "lon": 0.0}, {"lat": 0.0, "lon": 1.0}, {"lat": 1.0, "lon": 1.0}]
        with pytest.raises(ConstraintValidationError):
            _normalize_polygon(poly)


def test_rejects_out_of_range() -> None:
    poly = [{"lat": 0.0, "lon": 0.0}, {"lat": 0.0, "lon": 1.0}, {"lat": 99.0, "lon": 1.0}]
    with pytest.raises(ConstraintValidationError):
        _normalize_polygon(poly)


def test_rejects_too_few_distinct_vertices() -> None:
    with pytest.raises(ConstraintValidationError):
        _normalize_polygon([{"lat": 0.0, "lon": 0.0}, {"lat": 1.0, "lon": 1.0}])


def test_rejects_degenerate_collinear_polygon() -> None:
    poly = [{"lat": 0.0, "lon": 0.0}, {"lat": 0.0, "lon": 1.0}, {"lat": 0.0, "lon": 2.0}]
    with pytest.raises(ConstraintValidationError):
        _normalize_polygon(poly)


def test_rejects_self_intersecting_polygon() -> None:
    bowtie = [
        {"lat": 0.0, "lon": 0.0},
        {"lat": 1.0, "lon": 1.0},
        {"lat": 0.0, "lon": 1.0},
        {"lat": 1.0, "lon": 0.0},
    ]
    with pytest.raises(ConstraintValidationError):
        _normalize_polygon(bowtie)


def test_rejects_interior_duplicate_vertex() -> None:
    # A duplicate that is *not* a closing repeat is malformed and rejected rather
    # than silently dropped (which would change the polygon's shape).
    poly = [
        {"lat": 0.0, "lon": 0.0},
        {"lat": 0.0, "lon": 1.0},
        {"lat": 0.0, "lon": 1.0},
        {"lat": 1.0, "lon": 1.0},
    ]
    with pytest.raises(ConstraintValidationError):
        _normalize_polygon(poly)


def test_store_create_rejects_bad_geometry(tmp_path) -> None:
    store = OperationalConstraintsStore(tmp_path / "constraints.db")
    with pytest.raises(ConstraintValidationError):
        store.create(
            kind="blockage",
            name="degenerate",
            polygon=[{"lat": 0.0, "lon": 0.0}, {"lat": 0.0, "lon": 1.0}, {"lat": 0.0, "lon": 2.0}],
        )
    created = store.create(kind="blockage", name="good", polygon=VALID_SQUARE)
    assert created["version"] == 1
    assert len(created["polygon"]) == 4
