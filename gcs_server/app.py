from __future__ import annotations

import asyncio
from datetime import datetime
import os
import sys
import uuid
import warnings
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

try:
    from langchain_core._api.deprecation import LangChainPendingDeprecationWarning
except Exception:  # pragma: no cover - defensive for older langchain_core versions
    LangChainPendingDeprecationWarning = Warning  # type: ignore[assignment]

warnings.filterwarnings(
    "ignore",
    message=r"The default value of `allowed_objects` will change in a future version\..*",
    category=LangChainPendingDeprecationWarning,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gcs_server.ai.agent_traces import AgentTraceStore
from gcs_server.ai.chat_service import AIChatService
from gcs_server.ai.context_service import AIContextService
from gcs_server.ai.graph_runtime import PlanningShellGraphRuntime
from gcs_server.ai.intent_service import IntentService
from gcs_server.ai.tool_registry import ToolRegistry
from gcs_server.config import load_config, save_config
from gcs_server.runtime import AppRuntime, GCS_DIR, build_runtime
from gcs_server.routers import replay as replay_router_module
from gcs_server.routers import settings as settings_router_module
from gcs_server.routers import llm as llm_router_module
from gcs_server.routers import ai as ai_router_module
from gcs_server.routers import device_config as device_config_router_module
from gcs_server.routers import mission_lifecycle as mission_lifecycle_router_module
from gcs_server.routers.ai import AIInflightStreamManager
from gcs_server.routers.device_config import _rover_availability_policy
from gcs_server.routers.llm import _repair_stored_secret_refs

# Phase 2: LangGraph checkpointer for interrupt/resume approval
try:
    from langgraph.checkpoint.memory import MemorySaver as _MemorySaver
    _LANGGRAPH_CHECKPOINTER_AVAILABLE = True
except ImportError:
    _MemorySaver = None  # type: ignore[assignment,misc]
    _LANGGRAPH_CHECKPOINTER_AVAILABLE = False

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _resolve_gcs_data_path(path: object) -> Path:
    data_path = Path(str(path or ""))
    if data_path.is_absolute():
        return data_path
    return GCS_DIR / data_path


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    if _repair_stored_secret_refs(config):
        save_config(config)
    runtime = await build_runtime(config)
    app.state.runtime = runtime
    _tool_registry = ToolRegistry()
    agent_trace_store = AgentTraceStore(
        _resolve_gcs_data_path(config.logging.get("agent_trace_dir", "data/agent_traces"))
    )
    app.state.agent_trace_store = agent_trace_store
    app.state.ai_chat_service = AIChatService(
        runtime.ai_store,
        secret_resolver=runtime.secret_store.get_secret,
        tool_registry=_tool_registry,
        trace_store=agent_trace_store,
    )
    app.state.ai_inflight_streams = AIInflightStreamManager()
    _checkpointer = _MemorySaver() if _LANGGRAPH_CHECKPOINTER_AVAILABLE else None
    app.state.planning_shell_runtime = PlanningShellGraphRuntime(
        app_runtime=runtime,
        tool_registry=_tool_registry,
        context_service=AIContextService(runtime),
        intent_service=IntentService(),
        draft_service=runtime.mission_draft_service,
        ai_session_store=runtime.ai_store,
        secret_resolver=runtime.secret_store.get_secret,
        checkpointer=_checkpointer,
        trace_store=agent_trace_store,
    )
    await runtime.control_service.start()
    await runtime.mqtt_runtime.start()
    try:
        yield
    finally:
        if runtime.replay_store.current_session_id:
            runtime.replay_store.finish_session(runtime.replay_store.current_session_id, reason="runtime_shutdown")
        await runtime.control_service.stop()
        await runtime.mqtt_runtime.stop()
        runtime.ai_executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="Remote Rover GCS", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(replay_router_module.router)
app.include_router(settings_router_module.router)
app.include_router(llm_router_module.router)
app.include_router(ai_router_module.router)
app.include_router(device_config_router_module.router)
app.include_router(mission_lifecycle_router_module.router)


@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    response: Response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/setup/") or path.startswith("/settings") or path.startswith("/ai") or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def _runtime(request_or_socket: Request | WebSocket) -> AppRuntime:
    return request_or_socket.app.state.runtime


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
async def chrome_devtools_probe() -> Response:
    return Response(status_code=204)


@app.get("/settings")
async def settings_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "settings.html")


@app.get("/ai")
async def ai_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "ai.html")


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
    data["rover_availability"] = _rover_availability_policy(runtime.config)
    return data


@app.get("/api/config")
async def get_config(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    return {
        "key_bindings": runtime.config.key_bindings,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    runtime = _runtime(websocket)
    client_id = websocket.query_params.get("client_id") or uuid.uuid4().hex[:12]
    await runtime.ws_manager.connect(client_id, websocket)
    await runtime.mqtt_runtime.publish_presence_snapshot()
    snapshot = await runtime.state_store.snapshot()
    snapshot["simulation"] = runtime.config.simulation
    snapshot["rover_availability"] = _rover_availability_policy(runtime.config)
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
    print(f"[gcs_server] Starting at {datetime.now().astimezone().isoformat()}", flush=True)
    uvicorn.run(
        app,
        host=str(config.gcs["host"]),
        port=int(config.gcs["port"]),
        reload=False,
    )
