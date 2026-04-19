from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

try:
    from gcs_server.config import load_config, save_config
    from gcs_server.runtime import AppRuntime, build_runtime
    from gcs_server.scene_map import get_scene_map_payload
except ModuleNotFoundError:
    from config import load_config, save_config
    from runtime import AppRuntime, build_runtime
    from scene_map import get_scene_map_payload

STATIC_DIR = Path(__file__).resolve().parent / "static"
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    runtime = await build_runtime(config)
    app.state.runtime = runtime
    await runtime.control_service.start()
    await runtime.mqtt_runtime.start()
    try:
        yield
    finally:
        if runtime.replay_store.current_session_id:
            runtime.replay_store.finish_session(runtime.replay_store.current_session_id, reason="runtime_shutdown")
        await runtime.control_service.stop()
        await runtime.mqtt_runtime.stop()


app = FastAPI(title="Remote Rover GCS", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    response: Response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/setup/") or path.startswith("/settings") or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def _runtime(request_or_socket: Request | WebSocket) -> AppRuntime:
    return request_or_socket.app.state.runtime


def _connectivity_payload(config) -> dict[str, Any]:
    return {
        "mqtt": {
            "broker_host": config.mqtt.get("broker_host", ""),
            "broker_port": int(config.mqtt.get("broker_port", 1883)),
            "topic_prefix": config.mqtt.get("topic_prefix", ""),
            "client_id": config.mqtt.get("client_id", ""),
            "control_topic": config.mqtt.get("control_topic", "control/manual"),
            "state_topic": config.mqtt.get("state_topic", "telemetry/state"),
            "camera_topic": config.mqtt.get("camera_topic", "camera-feed"),
            "control_hz": int(config.mqtt.get("control_hz", 20)),
        },
        "simulation": {
            "backend": str(config.simulation.get("backend", "3d-env")) or "3d-env",
        },
    }


def _resolve_backend_config_path(path_text: str) -> Path:
    cleaned = (path_text or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="path is required")

    raw_path = Path(cleaned)
    resolved = raw_path.resolve(strict=False) if raw_path.is_absolute() else (CONFIG_DIR / raw_path).resolve(strict=False)
    config_root = CONFIG_DIR.resolve(strict=False)
    try:
        resolved.relative_to(config_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="path must stay inside the config directory") from exc
    return resolved


def _load_existing_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON at {path}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="backend config file must contain a top-level JSON object")
    return data


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/settings")
async def settings_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "settings.html")


@app.get("/api/health")
async def health(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    snapshot = await runtime.state_store.snapshot()
    return {"ok": True, "broker": snapshot["broker"]}


@app.get("/api/snapshot")
async def snapshot(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    data = await runtime.state_store.snapshot()
    data["simulation"] = runtime.config.simulation
    return data


@app.get("/api/config")
async def get_config(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    return runtime.config.raw


@app.get("/api/simulation-config")
async def get_simulation_config(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    return {
        "simulation": runtime.config.simulation,
        "logging": {
            "replay_db_path": str(runtime.replay_store.db_path),
            "current_session_id": runtime.replay_store.current_session_id,
        },
    }


@app.post("/api/simulation-config")
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


@app.get("/api/mqtt-config")
async def get_mqtt_config(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    return {
        "mqtt": runtime.config.mqtt,
        "settings_path": str(runtime.config.settings_path),
    }


@app.post("/api/mqtt-config")
async def set_mqtt_config(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    mqtt_payload = payload.get("mqtt")
    if not isinstance(mqtt_payload, dict):
        raise HTTPException(status_code=400, detail="mqtt object is required")

    current = dict(runtime.config.mqtt)
    updated = {
        "broker_host": str(mqtt_payload.get("broker_host", current.get("broker_host", ""))).strip(),
        "broker_port": int(mqtt_payload.get("broker_port", current.get("broker_port", 1883))),
        "topic_prefix": str(mqtt_payload.get("topic_prefix", current.get("topic_prefix", ""))).strip(),
        "client_id": str(mqtt_payload.get("client_id", current.get("client_id", ""))).strip(),
        "control_topic": str(mqtt_payload.get("control_topic", current.get("control_topic", "control/manual"))).strip(),
        "state_topic": str(mqtt_payload.get("state_topic", current.get("state_topic", "telemetry/state"))).strip(),
        "camera_topic": str(mqtt_payload.get("camera_topic", current.get("camera_topic", "camera-feed"))).strip(),
        "control_hz": int(mqtt_payload.get("control_hz", current.get("control_hz", 20))),
    }
    if not updated["broker_host"]:
        raise HTTPException(status_code=400, detail="broker_host is required")
    if updated["broker_port"] <= 0:
        raise HTTPException(status_code=400, detail="broker_port must be positive")
    if updated["control_hz"] <= 0:
        raise HTTPException(status_code=400, detail="control_hz must be positive")

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


@app.post("/api/connectivity/load-from-path")
async def load_connectivity_from_path(request: Request) -> JSONResponse:
    payload = await request.json()
    resolved_path = _resolve_backend_config_path(str(payload.get("path", "")))
    if not resolved_path.exists():
        raise HTTPException(status_code=404, detail="config file not found")

    config = load_config(resolved_path)
    result = _connectivity_payload(config)
    result["resolved_path"] = str(resolved_path)
    return JSONResponse(result)


@app.post("/api/connectivity/save-to-path")
async def save_connectivity_to_path(request: Request) -> JSONResponse:
    payload = await request.json()
    resolved_path = _resolve_backend_config_path(str(payload.get("path", "")))

    mqtt_payload = payload.get("mqtt")
    simulation_payload = payload.get("simulation")
    if not isinstance(mqtt_payload, dict):
        raise HTTPException(status_code=400, detail="mqtt object is required")
    if simulation_payload is not None and not isinstance(simulation_payload, dict):
        raise HTTPException(status_code=400, detail="simulation must be an object")

    existing = _load_existing_json_dict(resolved_path)
    mqtt_out = dict(existing.get("mqtt", {})) if isinstance(existing.get("mqtt"), dict) else {}
    mqtt_out.update({
        "broker_host": str(mqtt_payload.get("broker_host", "")).strip(),
        "broker_port": int(mqtt_payload.get("broker_port", 1883)),
        "topic_prefix": str(mqtt_payload.get("topic_prefix", "")).strip(),
        "client_id": str(mqtt_payload.get("client_id", "")).strip(),
        "control_topic": str(mqtt_payload.get("control_topic", "control/manual")).strip(),
        "state_topic": str(mqtt_payload.get("state_topic", "telemetry/state")).strip(),
        "camera_topic": str(mqtt_payload.get("camera_topic", "camera-feed")).strip(),
        "control_hz": int(mqtt_payload.get("control_hz", 20)),
    })
    existing["mqtt"] = mqtt_out

    simulation_out = dict(existing.get("simulation", {})) if isinstance(existing.get("simulation"), dict) else {}
    simulation_backend = str((simulation_payload or {}).get("backend", simulation_out.get("backend", "3d-env"))).strip() or "3d-env"
    simulation_out["backend"] = simulation_backend
    existing["simulation"] = simulation_out

    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    with open(resolved_path, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=2)
        fh.write("\n")

    return JSONResponse({
        "ok": True,
        "resolved_path": str(resolved_path),
        "mqtt": mqtt_out,
        "simulation": {"backend": simulation_backend},
    })


@app.get("/api/replay/sessions")
async def replay_sessions(request: Request, limit: int = 100) -> dict[str, Any]:
    runtime = _runtime(request)
    return {
        "sessions": runtime.replay_store.list_sessions(limit=limit),
        "current_session_id": runtime.replay_store.current_session_id,
    }


@app.post("/api/replay/sessions/rollover")
async def rollover_replay_session(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    reason = str(payload.get("reason", "manual_rollover"))
    session_id = runtime.replay_store.rollover_session(reason=reason)
    return JSONResponse({"ok": True, "current_session_id": session_id})


@app.get("/api/replay/sessions/{session_id}")
async def replay_session_detail(session_id: str, request: Request, limit: int = 2000) -> dict[str, Any]:
    runtime = _runtime(request)
    session = runtime.replay_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {
        "session": session,
        "timeline": runtime.replay_store.get_session_timeline(session_id, limit=limit),
    }


@app.delete("/api/replay/sessions/{session_id}")
async def delete_replay_session(session_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    try:
        deleted = runtime.replay_store.delete_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="session not found")
    return JSONResponse({
        "ok": True,
        "deleted_session_id": session_id,
        "current_session_id": runtime.replay_store.current_session_id,
    })


@app.get("/api/replay/scene-map")
async def replay_scene_map(backend: str = "3d-env", grid_size: int = 128) -> dict[str, Any]:
    try:
        return get_scene_map_payload(backend=backend, grid_size=grid_size)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/video-mode")
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
    await runtime.ws_manager.broadcast({"type": "video_mode", "data": modes})
    return JSONResponse({"ok": True, "video": modes})


@app.post("/api/controller/{action}")
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


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    runtime = _runtime(websocket)
    client_id = websocket.query_params.get("client_id") or uuid.uuid4().hex[:12]
    await runtime.ws_manager.connect(client_id, websocket)
    await runtime.mqtt_runtime.publish_presence_snapshot()
    snapshot = await runtime.state_store.snapshot()
    snapshot["simulation"] = runtime.config.simulation
    await runtime.ws_manager.send(client_id, {
        "type": "snapshot",
        "client_id": client_id,
        "data": snapshot,
    })

    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")
            if msg_type == "control":
                ok = await runtime.control_service.set_buttons(client_id, message.get("buttons", {}))
                if not ok:
                    await runtime.ws_manager.send(client_id, {
                        "type": "error",
                        "message": "Control rejected: client is not the active controller.",
                    })
                controller = await runtime.state_store.controller_snapshot()
                await runtime.ws_manager.broadcast({"type": "controller", "data": controller})
            elif msg_type == "control_release":
                await runtime.control_service.clear_buttons(client_id)
            elif msg_type == "ping":
                await runtime.ws_manager.send(client_id, {"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await runtime.control_service.clear_buttons(client_id)
        await runtime.state_store.release_controller(client_id)
        controller = await runtime.state_store.controller_snapshot()
        await runtime.ws_manager.broadcast({"type": "controller", "data": controller})
        await runtime.ws_manager.disconnect(client_id)
        await runtime.mqtt_runtime.publish_presence_snapshot()


@app.get("/setup/mqtt")
async def mqtt_setup_page() -> RedirectResponse:
    return RedirectResponse(url="/settings?tab=connectivity", status_code=307)


@app.get("/replay")
async def replay_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "replay.html")


if __name__ == "__main__":
    config = load_config()
    uvicorn.run(
        app,
        host=str(config.gcs["host"]),
        port=int(config.gcs["port"]),
        reload=False,
    )
