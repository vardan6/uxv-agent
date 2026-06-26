from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from gcs_server.config import save_config
from gcs_server.runtime import AppRuntime

router = APIRouter()

DEFAULT_ROVER_AVAILABILITY_POLICY = {
    "connected_threshold_seconds": 2,
    "unavailable_threshold_seconds": 60,
    "rollover_on_reconnect": True,
}


def _runtime(request: Request) -> AppRuntime:
    return request.app.state.runtime


def _parse_int_field(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{name} must be an integer") from exc


def _rover_availability_policy_from_mqtt(mqtt: dict[str, Any] | None) -> dict[str, Any]:
    raw_policy = mqtt.get("rover_availability", {}) if isinstance(mqtt, dict) else {}
    policy = raw_policy if isinstance(raw_policy, dict) else {}
    connected = policy.get("connected_threshold_seconds", DEFAULT_ROVER_AVAILABILITY_POLICY["connected_threshold_seconds"])
    unavailable = policy.get("unavailable_threshold_seconds", DEFAULT_ROVER_AVAILABILITY_POLICY["unavailable_threshold_seconds"])
    rollover = policy.get("rollover_on_reconnect", DEFAULT_ROVER_AVAILABILITY_POLICY["rollover_on_reconnect"])
    try:
        connected_value = max(0, int(connected))
    except (TypeError, ValueError):
        connected_value = DEFAULT_ROVER_AVAILABILITY_POLICY["connected_threshold_seconds"]
    try:
        unavailable_value = max(1, int(unavailable))
    except (TypeError, ValueError):
        unavailable_value = DEFAULT_ROVER_AVAILABILITY_POLICY["unavailable_threshold_seconds"]
    if unavailable_value < connected_value:
        unavailable_value = connected_value
    return {
        "connected_threshold_seconds": connected_value,
        "unavailable_threshold_seconds": unavailable_value,
        "rollover_on_reconnect": bool(rollover),
    }


def _rover_availability_policy(config: Any) -> dict[str, Any]:
    mqtt = config.mqtt if hasattr(config, "mqtt") else {}
    return _rover_availability_policy_from_mqtt(mqtt if isinstance(mqtt, dict) else {})


@router.get("/api/simulation-config")
async def get_simulation_config(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    return {
        "simulation": runtime.config.simulation,
        "logging": {
            "replay_db_path": str(runtime.replay_store.db_path),
            "current_session_id": runtime.replay_store.current_session_id,
        },
    }


@router.post("/api/simulation-config")
async def set_simulation_config(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    simulation_payload = payload.get("simulation")
    if not isinstance(simulation_payload, dict):
        raise HTTPException(status_code=400, detail="simulation object is required")

    current = dict(runtime.config.simulation)
    updated = {
        "backend": str(simulation_payload.get("backend", current.get("backend", "3d-env"))).strip() or "3d-env",
        "backend_version": str(simulation_payload.get("backend_version", current.get("backend_version", "dev"))).strip() or "dev",
        "available_backends": list(current.get("available_backends", ["3d-env", "rover-sim-next"])),
    }
    runtime.config.raw["simulation"] = updated
    save_config(runtime.config)
    runtime.replay_store.update_backend(updated["backend"], updated["backend_version"])
    runtime.replay_store.rollover_session(reason=f"backend_change:{updated['backend']}")
    runtime.replay_store.log_runtime_event("simulation_backend_changed", updated)
    await runtime.ws_manager.broadcast({"type": "simulation_config", "data": updated})
    return JSONResponse({"ok": True, "simulation": updated})


@router.get("/api/mqtt-config")
async def get_mqtt_config(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    return {
        "mqtt": runtime.config.mqtt,
        "settings_path": str(runtime.config.settings_path),
    }


@router.post("/api/mqtt-config")
async def set_mqtt_config(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    mqtt_payload = payload.get("mqtt")
    if not isinstance(mqtt_payload, dict):
        raise HTTPException(status_code=400, detail="mqtt object is required")

    current = dict(runtime.config.mqtt)
    updated = dict(current)
    updated.update({
        "broker_host": str(mqtt_payload.get("broker_host", current.get("broker_host", ""))).strip(),
        "broker_port": _parse_int_field(mqtt_payload.get("broker_port", current.get("broker_port", 1883)), "broker_port"),
        "topic_prefix": str(mqtt_payload.get("topic_prefix", current.get("topic_prefix", ""))).strip(),
        "client_id": str(mqtt_payload.get("client_id", current.get("client_id", ""))).strip(),
        "control_topic": str(mqtt_payload.get("control_topic", current.get("control_topic", "control/manual"))).strip(),
        "state_topic": str(mqtt_payload.get("state_topic", current.get("state_topic", "telemetry/state"))).strip(),
        "camera_topic": str(mqtt_payload.get("camera_topic", current.get("camera_topic", "camera-feed"))).strip(),
        "control_hz": _parse_int_field(mqtt_payload.get("control_hz", current.get("control_hz", 20)), "control_hz"),
    })
    if not updated["broker_host"]:
        raise HTTPException(status_code=400, detail="broker_host is required")
    if updated["broker_port"] <= 0:
        raise HTTPException(status_code=400, detail="broker_port must be positive")
    if updated["control_hz"] <= 0:
        raise HTTPException(status_code=400, detail="control_hz must be positive")
    rover_availability_payload = mqtt_payload.get("rover_availability")
    if rover_availability_payload is not None and not isinstance(rover_availability_payload, dict):
        raise HTTPException(status_code=400, detail="mqtt.rover_availability must be an object")
    updated["rover_availability"] = _rover_availability_policy_from_mqtt({
        **updated,
        **({"rover_availability": rover_availability_payload} if rover_availability_payload is not None else {}),
    })

    runtime.config.raw.setdefault("mqtt", {}).update(updated)
    save_config(runtime.config)
    await runtime.reconfigure_mqtt(runtime.config.mqtt)
    snapshot = await runtime.state_store.snapshot()
    await runtime.ws_manager.broadcast({"type": "broker", "data": snapshot["broker"]})
    return JSONResponse({
        "ok": True,
        "mqtt": runtime.config.mqtt,
        "settings_path": str(runtime.config.settings_path),
    })


@router.post("/api/video-mode")
async def set_video_mode(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    enabled = bool(payload.get("enabled", True))
    ingest_mode = str(payload.get("ingest_mode", runtime.config.video["ingest_mode"]))
    delivery_mode = str(payload.get("delivery_mode", runtime.config.video["delivery_mode"]))

    runtime.config.raw.setdefault("video", {})["enabled"] = enabled
    runtime.config.raw["video"]["ingest_mode"] = ingest_mode
    runtime.config.raw["video"]["delivery_mode"] = delivery_mode
    save_config(runtime.config)

    modes = await runtime.state_store.set_video_modes(enabled, ingest_mode, delivery_mode)
    await runtime.ws_manager.broadcast({"type": "video", "data": modes})
    return JSONResponse({"ok": True, "video": modes})


@router.post("/api/controller/{action}")
async def controller_action(action: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    client_id = str(payload.get("client_id", "")).strip()
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required")

    if action == "take":
        ok = await runtime.state_store.try_claim_controller(client_id)
        runtime.replay_store.log_runtime_event("controller_take_attempt", {"client_id": client_id, "ok": ok})
    elif action == "release":
        ok = await runtime.state_store.release_controller(client_id)
        await runtime.control_service.clear_buttons(client_id)
        runtime.replay_store.log_runtime_event("controller_release_attempt", {"client_id": client_id, "ok": ok})
    else:
        raise HTTPException(status_code=404, detail="unknown action")

    controller = await runtime.state_store.controller_snapshot()
    await runtime.ws_manager.broadcast({"type": "controller", "data": controller})
    await runtime.mqtt_runtime.publish_presence_snapshot()
    return JSONResponse({"ok": ok, "controller": controller})
