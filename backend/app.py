from __future__ import annotations

import asyncio
from datetime import datetime
import os
import re
import sys
import uuid
import warnings
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
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

from backend.ai.agent_traces import AgentTraceStore
from backend.ai.chat_service import AIChatService
from backend.ai.tool_registry import ToolRegistry
from backend.ai.vehicle_profile import resolve_active_profile
from backend.config import load_config, save_config
from backend.runtime import AppRuntime, GCS_DIR, build_runtime
from backend.routers import replay as replay_router_module
from backend.routers import settings as settings_router_module
from backend.routers import llm as llm_router_module
from backend.routers import ai as ai_router_module
from backend.routers import device_config as device_config_router_module
from backend.routers import mission_lifecycle as mission_lifecycle_router_module
from backend.routers import operational_constraints as operational_constraints_router_module
from backend.routers import rag as rag_router_module
from backend.routers.ai import AIInflightStreamManager
from backend.routers.device_config import _rover_availability_policy
from backend.mavlink_telemetry import MavlinkTelemetryBridge
from backend.routers.llm import _repair_stored_secret_refs

REPO_ROOT = Path(__file__).resolve().parent.parent
# static/ dissolved into frontend-vanilla/ (pages) + map/ (shared widget, ADR
# 0037); STATIC_DIR keeps the name because vanilla pages are still served at
# /static for zero client-side churn.
STATIC_DIR = REPO_ROOT / "frontend-vanilla"
MAP_DIR = REPO_ROOT / "map"
DOCS_DIR = REPO_ROOT / "docs"
# Greenfield operator console (ADR 0030): Vite builds here; served under /app
# with an SPA fallback. /api + /ws remain the backend contract for all clients.
WEBAPP_DIR = Path(__file__).resolve().parent / "webapp"


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
    _tool_registry = ToolRegistry(profile_resolver=lambda: resolve_active_profile(config))
    app.state.tool_registry = _tool_registry
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
    await runtime.control_service.start()
    await runtime.mqtt_runtime.start()
    mavlink_telemetry_url = os.environ.get("MAVLINK_TELEMETRY_URL", "").strip()
    _mavlink_bridge: MavlinkTelemetryBridge | None = None
    if mavlink_telemetry_url:
        _mavlink_bridge = MavlinkTelemetryBridge(
            mavlink_telemetry_url,
            asyncio.get_running_loop(),
            runtime.ws_manager.broadcast,
        )
        _mavlink_bridge.start()
    try:
        yield
    finally:
        if _mavlink_bridge:
            _mavlink_bridge.stop()
        if runtime.replay_store.current_session_id:
            runtime.replay_store.finish_session(runtime.replay_store.current_session_id, reason="runtime_shutdown")
        await runtime.control_service.stop()
        await runtime.mqtt_runtime.stop()
        runtime.ai_executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="Remote Rover GCS", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/map", StaticFiles(directory=MAP_DIR), name="map")
if (WEBAPP_DIR / "assets").is_dir():
    app.mount("/app/assets", StaticFiles(directory=WEBAPP_DIR / "assets"), name="webapp-assets")
app.include_router(replay_router_module.router)
app.include_router(settings_router_module.router)
app.include_router(llm_router_module.router)
app.include_router(ai_router_module.router)
app.include_router(device_config_router_module.router)
app.include_router(mission_lifecycle_router_module.router)
app.include_router(operational_constraints_router_module.router)
app.include_router(rag_router_module.router)


@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    response: Response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/dashboard") or path.startswith("/setup/") or path.startswith("/settings") or path.startswith("/ai") or path.startswith("/mission-console") or path.startswith("/static/") or path == "/app" or (path.startswith("/app/") and not path.startswith("/app/assets/")):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def _runtime(request_or_socket: Request | WebSocket) -> AppRuntime:
    return request_or_socket.app.state.runtime


@app.get("/")
async def mission_console_index() -> RedirectResponse:
    return RedirectResponse(url="/mission-console", status_code=307)


@app.get("/dashboard")
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


@app.get("/mission-console")
async def mission_console_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "mission-console.html")


def _slugify_heading(text: str) -> str:
    """GitHub-ish heading slug. Must match `slugifyHeading` in static/ai.js."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _inject_heading_anchors(html: str) -> str:
    """Add stable `id` slugs to rendered <h1>..<h6> so cited links can deep-link."""
    used: dict[str, int] = {}

    def _add_id(match: "re.Match[str]") -> str:
        level, inner = match.group(1), match.group(2)
        text = re.sub(r"<[^>]+>", "", inner)  # strip inline markup
        slug = _slugify_heading(text)
        if not slug:
            return match.group(0)
        count = used.get(slug, 0)
        used[slug] = count + 1
        if count:
            slug = f"{slug}-{count}"
        return f'<h{level} id="{slug}">{inner}</h{level}>'

    return re.sub(r"<h([1-6])>(.*?)</h\1>", _add_id, html, flags=re.DOTALL)


@app.get("/docs/{path:path}")
async def docs_viewer(path: str) -> HTMLResponse:
    resolved = (DOCS_DIR / path).resolve()
    if not str(resolved).startswith(str(DOCS_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        from markdown_it import MarkdownIt
        md = MarkdownIt()
        body_html = md.render(resolved.read_text(encoding="utf-8"))
        body_html = _inject_heading_anchors(body_html)
    except ImportError:
        body_html = f"<pre>{resolved.read_text(encoding='utf-8')}</pre>"
    title = resolved.stem
    return HTMLResponse(content=f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="/static/style.css">
<style>
  body {{ max-width: 860px; margin: 32px auto; padding: 0 20px 60px; font-family: inherit; }}
  .docs-back {{ display:inline-block; margin-bottom:18px; color:var(--muted); font-size:0.82rem; text-decoration:none; }}
  .docs-back:hover {{ color:var(--text); }}
  .docs-body h1,.docs-body h2,.docs-body h3,.docs-body h4,.docs-body h5,.docs-body h6 {{ margin-top:1.6em; scroll-margin-top:24px; }}
  .docs-body pre {{ padding:10px 14px; border-radius:8px; background:var(--panel-strong,#1e1e1e); overflow-x:auto; }}
  .docs-body code {{ font-size:0.88em; }}
  .docs-body table {{ border-collapse:collapse; width:100%; }}
  .docs-body th,.docs-body td {{ padding:6px 10px; border:1px solid var(--line,#333); text-align:left; }}
  .docs-body blockquote {{ margin:0; padding:8px 14px; border-left:3px solid var(--accent,#4a9); color:var(--muted); }}
</style>
</head>
<body>
<a class="docs-back" href="javascript:history.back()">&#8592; back</a>
<div class="docs-body">{body_html}</div>
</body>
</html>""")


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
            op = message.get("op")
            topic = message.get("topic")
            if op == "subscribe" and isinstance(topic, str):
                await runtime.ws_manager.subscribe(client_id, topic)
            elif op == "unsubscribe" and isinstance(topic, str):
                await runtime.ws_manager.unsubscribe(client_id, topic)
            elif msg_type == "control":
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


def _webapp_index() -> FileResponse:
    index = WEBAPP_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(
            status_code=503,
            detail="Operator console build missing. Run `npm run build` in frontend/.",
        )
    return FileResponse(index)


def _webapp_file(name: str) -> FileResponse:
    target = WEBAPP_DIR / name
    if not target.is_file():
        raise HTTPException(
            status_code=503,
            detail=f"Operator console asset missing: {name}. Run `npm run build` in frontend/.",
        )
    return FileResponse(target)


@app.get("/app")
async def operator_console_index() -> FileResponse:
    return _webapp_index()


@app.get("/app/popout.html")
async def operator_console_popout() -> FileResponse:
    return _webapp_file("popout.html")


@app.get("/app/{path:path}")
async def operator_console_spa(path: str) -> FileResponse:
    # SPA fallback: client-side routes resolve to index.html. Real build assets
    # are served by the /app/assets static mount, which takes precedence.
    return _webapp_index()


if __name__ == "__main__":
    config = load_config()
    print(f"[backend] Starting at {datetime.now().astimezone().isoformat()}", flush=True)
    uvicorn.run(
        app,
        host=str(config.gcs["host"]),
        port=int(config.gcs["port"]),
        reload=False,
    )
