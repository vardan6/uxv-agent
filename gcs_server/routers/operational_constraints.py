"""REST CRUD for operational constraints (ADR 0025, V2 contract).

Allowed corridors and blockages are deployment-wide *planning* data. These are
not the per-mission geofence and never touch the mission-revision path. `hard`
means the planner refuses to produce a violating route — it is not a live
runtime containment guarantee; the UI labels the feature "Planning constraints".
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from gcs_server.ai.operational_constraints_store import (
    ConstraintConflict,
    ConstraintNotFound,
    ConstraintValidationError,
)
from gcs_server.runtime import AppRuntime

router = APIRouter()


def _store(request: Request):
    runtime: AppRuntime = request.app.state.runtime
    return runtime.operational_constraints_store


def _require_int(value: Any, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{field} must be an integer")


@router.get("/api/operational-constraints")
async def list_operational_constraints(request: Request) -> dict[str, Any]:
    return {"constraints": _store(request).list_constraints()}


@router.post("/api/operational-constraints")
async def create_operational_constraint(request: Request) -> JSONResponse:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="constraint payload must be an object")
    try:
        created = _store(request).create(
            kind=payload.get("kind"),
            name=payload.get("name"),
            polygon=payload.get("polygon"),
            rule=payload.get("rule", "hard"),
            enabled=payload.get("enabled", True),
        )
    except ConstraintValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"ok": True, "constraint": created}, status_code=201)


@router.put("/api/operational-constraints/{constraint_id}")
async def update_operational_constraint(constraint_id: str, request: Request) -> JSONResponse:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="constraint payload must be an object")
    if "expected_version" not in payload:
        raise HTTPException(status_code=400, detail="expected_version is required")
    expected_version = _require_int(payload.get("expected_version"), "expected_version")
    try:
        updated = _store(request).update(
            constraint_id,
            expected_version=expected_version,
            name=payload.get("name"),
            polygon=payload.get("polygon"),
            rule=payload.get("rule"),
            enabled=payload.get("enabled"),
        )
    except ConstraintNotFound as exc:
        raise HTTPException(status_code=404, detail="constraint not found") from exc
    except ConstraintConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ConstraintValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"ok": True, "constraint": updated})


@router.delete("/api/operational-constraints/{constraint_id}")
async def delete_operational_constraint(
    constraint_id: str, request: Request, expected_version: int
) -> JSONResponse:
    try:
        _store(request).delete(constraint_id, expected_version=int(expected_version))
    except ConstraintNotFound as exc:
        raise HTTPException(status_code=404, detail="constraint not found") from exc
    except ConstraintConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse({"ok": True})
