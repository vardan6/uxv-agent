from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

try:
    from gcs_server.config import load_config, save_config
    from gcs_server.runtime import AppRuntime, build_runtime
except ModuleNotFoundError:
    from config import load_config, save_config
    from runtime import AppRuntime, build_runtime

STATIC_DIR = Path(__file__).resolve().parent / "static"


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
        await runtime.control_service.stop()
        await runtime.mqtt_runtime.stop()


app = FastAPI(title="Remote Rover GCS", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    response: Response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/setup/") or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def _runtime(request_or_socket: Request | WebSocket) -> AppRuntime:
    return request_or_socket.app.state.runtime


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    snapshot = await runtime.state_store.snapshot()
    return {"ok": True, "broker": snapshot["broker"]}


@app.get("/api/snapshot")
async def snapshot(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    return await runtime.state_store.snapshot()


@app.get("/api/config")
async def get_config(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    return runtime.config.raw


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
    elif action == "release":
        ok = await runtime.state_store.release_controller(client_id)
        await runtime.control_service.clear_buttons(client_id)
    else:
        raise HTTPException(status_code=404, detail="unknown action")

    controller = await runtime.state_store.controller_snapshot()
    await runtime.ws_manager.broadcast({"type": "controller", "data": controller})
    return JSONResponse({"ok": ok, "controller": controller})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    runtime = _runtime(websocket)
    client_id = websocket.query_params.get("client_id") or uuid.uuid4().hex[:12]
    await runtime.ws_manager.connect(client_id, websocket)
    snapshot = await runtime.state_store.snapshot()
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
            elif msg_type == "take_control":
                ok = await runtime.state_store.try_claim_controller(client_id)
                controller = await runtime.state_store.controller_snapshot()
                await runtime.ws_manager.broadcast({"type": "controller", "data": controller})
                await runtime.ws_manager.send(client_id, {"type": "take_control_result", "ok": ok})
            elif msg_type == "release_control":
                await runtime.control_service.clear_buttons(client_id)
                await runtime.state_store.release_controller(client_id)
                controller = await runtime.state_store.controller_snapshot()
                await runtime.ws_manager.broadcast({"type": "controller", "data": controller})
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


@app.get("/setup/mqtt")
async def mqtt_setup_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "mqtt-setup.html")


if __name__ == "__main__":
    config = load_config()
    uvicorn.run(
        app,
        host=str(config.gcs["host"]),
        port=int(config.gcs["port"]),
        reload=False,
    )
