from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import uuid
import warnings
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request as UrlRequest, urlopen

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
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

try:
    from gcs_server.ai.context_service import AIContextService
    from gcs_server.ai.chat_service import AIChatService, AI_CONTEXT_MESSAGE_LIMIT
    from gcs_server.ai.data_access import build_data_access_manifest
    from gcs_server.ai.agent_traces import AgentTraceStore
    from gcs_server.ai.graph_runtime import WorkbenchGraphRuntime
    from gcs_server.ai.intent_service import IntentService
    from gcs_server.ai.mission_draft_service import MissionDraftService, validate_draft_payload
    from gcs_server.ai.provider_registry import evict_model_cache, resolve_intent_provider
    from gcs_server.ai.retrieval import (
        build_loaded_data_refs,
        build_retrieval_citations,
        build_retrieved_sources,
        normalize_retrieval_request,
    )
    from gcs_server.ai.tool_registry import ToolRegistry, allowed_tool_names_for_source_controls
    from gcs_server.ai.session_store import normalize_source_controls
    from gcs_server.ai.workbench_graph import resume_workbench_graph, stream_workbench_graph
    from gcs_server.config import load_config, save_config
    from gcs_server.runtime import AppRuntime, GCS_DIR, build_runtime
    from gcs_server.scene_map import get_scene_map_payload
except ModuleNotFoundError:
    from ai.context_service import AIContextService
    from ai.chat_service import AIChatService, AI_CONTEXT_MESSAGE_LIMIT
    from ai.data_access import build_data_access_manifest
    from ai.agent_traces import AgentTraceStore
    from ai.graph_runtime import WorkbenchGraphRuntime
    from ai.intent_service import IntentService
    from ai.mission_draft_service import MissionDraftService, validate_draft_payload
    from ai.provider_registry import evict_model_cache, resolve_intent_provider
    from ai.retrieval import (
        build_loaded_data_refs,
        build_retrieval_citations,
        build_retrieved_sources,
        normalize_retrieval_request,
    )
    from ai.tool_registry import ToolRegistry, allowed_tool_names_for_source_controls
    from ai.session_store import normalize_source_controls
    from ai.workbench_graph import resume_workbench_graph, stream_workbench_graph
    from config import load_config, save_config
    from runtime import AppRuntime, GCS_DIR, build_runtime
    from scene_map import get_scene_map_payload

# Phase 2: LangGraph checkpointer for interrupt/resume approval
try:
    from langgraph.checkpoint.memory import MemorySaver as _MemorySaver
    _LANGGRAPH_CHECKPOINTER_AVAILABLE = True
except ImportError:
    _MemorySaver = None  # type: ignore[assignment,misc]
    _LANGGRAPH_CHECKPOINTER_AVAILABLE = False

STATIC_DIR = Path(__file__).resolve().parent / "static"
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

PROVIDER_TYPES = {
    "openrouter",
    "nvidia_nim",
    "openai",
    "anthropic",
    "google_gemini",
    "ollama",
    "lm_studio",
    "mistral",
    "cohere",
    "together",
    "groq",
    "huggingface",
    "openai_compatible",
}

MODEL_CATEGORIES = {"chat", "reasoning", "planner", "reporting", "embeddings", "vision", "tool_calling"}
SECRET_REF_PREFIX = "secret://"

ROUTING_PURPOSES = {
    "general_chat": "General Chat",
    "rover_intent_parser": "Rover Intent Parser",
    "mission_planner": "Mission Planner",
    "reporter": "Reporter",
    "embeddings": "Embeddings",
    "vision_object_description": "Vision / Object Description",
}

DEFAULT_ROVER_AVAILABILITY_POLICY = {
    "connected_threshold_seconds": 2,
    "unavailable_threshold_seconds": 60,
    "rollover_on_reconnect": True,
}


def _sanitize_secret_ref(value: Any) -> str:
    secret_ref = str(value or "").strip()
    if "=" in secret_ref:
        secret_ref = secret_ref.split("=", 1)[0].strip()
    if not secret_ref:
        return ""
    if not (secret_ref[0].isalpha() or secret_ref[0] == "_"):
        return ""
    if any(not (char.isalnum() or char == "_") for char in secret_ref):
        return ""
    return secret_ref


def _sanitize_stored_secret_ref(value: Any) -> str:
    secret_ref = str(value or "").strip()
    if not secret_ref.startswith(SECRET_REF_PREFIX):
        return ""
    return secret_ref


def _default_provider_secret_ref(provider_id: str) -> str:
    return f"{SECRET_REF_PREFIX}provider-{provider_id}"


def _redact_secret_text(value: Any) -> str:
    return re.sub(
        r"\b([A-Za-z_][A-Za-z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)[A-Za-z0-9_]*)=([^\s,;]+)",
        r"\1=********",
        str(value or ""),
        flags=re.IGNORECASE,
    )


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
    app.state.workbench_runtime = WorkbenchGraphRuntime(
        app_runtime=runtime,
        tool_registry=_tool_registry,
        context_service=AIContextService(runtime),
        intent_service=IntentService(),
        draft_service=runtime.mission_draft_service,
        ai_session_store=runtime.ai_store,
        secret_resolver=runtime.secret_store.get_secret,
        checkpointer=_checkpointer,
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


def _resolve_gcs_data_path(path: object) -> Path:
    data_path = Path(str(path or ""))
    if data_path.is_absolute():
        return data_path
    return GCS_DIR / data_path


app = FastAPI(title="Remote Rover GCS", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class _AIStreamRun:
    def __init__(self, run_id: str, session_id: str) -> None:
        self.run_id = run_id
        self.session_id = session_id
        self._lines: list[str] = []
        self._done = False
        self._condition = threading.Condition()

    def append(self, line: str) -> None:
        with self._condition:
            self._lines.append(line)
            self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            self._done = True
            self._condition.notify_all()

    def stream(self) -> Any:
        index = 0
        while True:
            with self._condition:
                while index >= len(self._lines) and not self._done:
                    self._condition.wait(timeout=0.25)
                if index < len(self._lines):
                    line = self._lines[index]
                    index += 1
                elif self._done:
                    break
                else:
                    continue
            yield line


class AIInflightStreamManager:
    def __init__(self) -> None:
        self._runs: dict[str, _AIStreamRun] = {}
        self._lock = threading.Lock()

    def start(self, runtime: AppRuntime, session_id: str, stream_factory: Any) -> _AIStreamRun:
        with self._lock:
            current = self._runs.get(session_id)
            if current is not None:
                raise ValueError("A response is already in progress for this session.")
            run = _AIStreamRun(run_id=f"ai-run-{uuid.uuid4().hex[:12]}", session_id=session_id)
            self._runs[session_id] = run

        def _worker() -> None:
            try:
                stream = stream_factory()
                for line in _stream_ai_events(stream):
                    run.append(line)
            finally:
                run.close()
                with self._lock:
                    active = self._runs.get(session_id)
                    if active is run:
                        self._runs.pop(session_id, None)

        runtime.ai_executor.submit(_worker)
        return run

    def get(self, session_id: str) -> _AIStreamRun | None:
        with self._lock:
            return self._runs.get(session_id)


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


def _ai_inflight_streams(request_or_socket: Request | WebSocket) -> AIInflightStreamManager:
    return request_or_socket.app.state.ai_inflight_streams


def _connectivity_payload(config) -> dict[str, Any]:
    rover_availability = _rover_availability_policy(config)
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
            "rover_availability": rover_availability,
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


def _rover_availability_policy(config) -> dict[str, Any]:
    mqtt = config.mqtt if hasattr(config, "mqtt") else {}
    return _rover_availability_policy_from_mqtt(mqtt if isinstance(mqtt, dict) else {})


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


def _provider_public(provider: dict[str, Any], runtime: AppRuntime | None = None) -> dict[str, Any]:
    out = dict(provider)
    auth_mode = str(out.get("auth_mode", "env_var")).strip()
    if auth_mode == "stored_secret":
        out["secret_ref"] = _sanitize_stored_secret_ref(out.get("secret_ref", ""))
        out["has_secret"] = bool(
            runtime
            and out["secret_ref"]
            and runtime.secret_store.has_secret(out["secret_ref"])
        )
    else:
        out["secret_ref"] = _sanitize_secret_ref(out.get("secret_ref", ""))
        out["has_secret"] = False
    out.pop("secret_value", None)
    last_check = out.get("last_check")
    if isinstance(last_check, dict):
        redacted_check = dict(last_check)
        if "message" in redacted_check:
            redacted_check["message"] = _redact_secret_text(redacted_check["message"])
        out["last_check"] = redacted_check
    return out


def _repair_stored_secret_refs(config: Any) -> bool:
    providers = config.raw.get("llm_providers", [])
    if not isinstance(providers, list):
        return False
    changed = False
    for index, provider in enumerate(providers):
        if not isinstance(provider, dict):
            continue
        auth_mode = str(provider.get("auth_mode", "")).strip()
        if auth_mode != "stored_secret":
            continue
        try:
            normalized = _normalize_provider(provider, provider)
        except HTTPException:
            continue
        if normalized != provider:
            providers[index] = normalized
            changed = True
    return changed


def _provider_export(provider: dict[str, Any]) -> dict[str, Any]:
    out = dict(provider)
    auth_mode = str(out.get("auth_mode", "")).strip()
    if auth_mode == "stored_secret":
        out["secret_ref"] = _sanitize_stored_secret_ref(out.get("secret_ref", ""))
    else:
        out["secret_ref"] = _sanitize_secret_ref(out.get("secret_ref", ""))
    out["has_secret"] = False
    out.pop("last_check", None)
    out.pop("secret_value", None)
    return out


def _normalize_context_window(value: Any) -> int | None:
    if value is None:
        return None
    try:
        n = int(value)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _normalize_capabilities(value: Any) -> list[str]:
    if isinstance(value, str):
        items = [part.strip() for part in value.replace(";", ",").split(",")]
    elif isinstance(value, list):
        items = [str(part).strip() for part in value]
    else:
        items = []
    return sorted({item for item in items if item})


def _normalize_provider(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    current = existing or {}
    provider_type = str(payload.get("provider_type", current.get("provider_type", "openai_compatible"))).strip()
    if provider_type not in PROVIDER_TYPES:
        raise HTTPException(status_code=400, detail="unsupported provider_type")

    display_name = str(payload.get("display_name", current.get("display_name", ""))).strip()
    if not display_name:
        raise HTTPException(status_code=400, detail="display_name is required")

    auth_mode = str(payload.get("auth_mode", current.get("auth_mode", "env_var"))).strip()
    if auth_mode not in {"env_var", "stored_secret", "none"}:
        raise HTTPException(status_code=400, detail="auth_mode must be env_var, stored_secret, or none")

    base_url = str(payload.get("base_url", current.get("base_url", ""))).strip()
    model_id = str(payload.get("model_id", current.get("model_id", ""))).strip()
    if not model_id:
        raise HTTPException(status_code=400, detail="model_id is required")

    provider_id = str(current.get("id") or payload.get("id") or f"provider-{uuid.uuid4().hex[:12]}").strip()
    normalized = {
        "id": provider_id,
        "display_name": display_name,
        "provider_type": provider_type,
        "auth_mode": auth_mode,
        "secret_ref": _sanitize_secret_ref(payload.get("secret_ref", current.get("secret_ref", ""))),
        "base_url": base_url,
        "model_id": model_id,
        "capabilities": _normalize_capabilities(payload.get("capabilities", current.get("capabilities", []))),
        "enabled": bool(payload.get("enabled", current.get("enabled", True))),
        "context_window": _normalize_context_window(payload.get("context_window", current.get("context_window"))),
        "last_check": current.get("last_check") or {"status": "not_tested"},
    }
    if auth_mode == "env_var" and not normalized["secret_ref"]:
        raise HTTPException(status_code=400, detail="secret_ref is required for env_var auth")
    if auth_mode == "stored_secret":
        normalized["secret_ref"] = _sanitize_stored_secret_ref(payload.get("secret_ref", current.get("secret_ref", "")))
        if not normalized["secret_ref"]:
            normalized["secret_ref"] = _default_provider_secret_ref(provider_id)
    if auth_mode == "none":
        normalized["secret_ref"] = ""
    return normalized


def _find_provider(runtime: AppRuntime, provider_id: str) -> tuple[int, dict[str, Any]]:
    providers = runtime.config.raw.setdefault("llm_providers", [])
    if not isinstance(providers, list):
        runtime.config.raw["llm_providers"] = []
        providers = runtime.config.raw["llm_providers"]
    for index, provider in enumerate(providers):
        if isinstance(provider, dict) and provider.get("id") == provider_id:
            return index, provider
    raise HTTPException(status_code=404, detail="provider not found")


def _http_json_probe(url: str, secret: str | None = None) -> tuple[bool, str]:
    headers = {"Accept": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    request = UrlRequest(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=8) as response:
            if 200 <= response.status < 300:
                return True, f"HTTP {response.status}"
            return False, f"HTTP {response.status}"
    except HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except URLError as exc:
        return False, str(exc.reason)
    except TimeoutError:
        return False, "request timed out"


def _check_provider(runtime: AppRuntime, provider: dict[str, Any], secret_override: str | None = None) -> dict[str, Any]:
    auth_mode = str(provider.get("auth_mode", "")).strip()
    if auth_mode == "env_var":
        secret_ref = str(provider.get("secret_ref", "")).strip()
        if not secret_ref:
            return {"status": "missing_key", "ok": False, "message": "missing environment variable name"}
        secret = os.environ.get(secret_ref)
        if not secret:
            return {"status": "missing_key", "ok": False, "message": f"environment variable {secret_ref} is not set"}
    elif auth_mode == "stored_secret":
        if secret_override is not None:
            secret = secret_override
        else:
            secret_ref = _sanitize_stored_secret_ref(provider.get("secret_ref", ""))
            if not secret_ref:
                return {"status": "missing_key", "ok": False, "message": "stored secret reference is missing"}
            try:
                secret = runtime.secret_store.get_secret(secret_ref)
            except KeyError:
                return {"status": "missing_key", "ok": False, "message": "stored API key is not set"}
        if not secret:
            return {"status": "missing_key", "ok": False, "message": "stored API key is empty"}
    else:
        secret = None

    provider_type = str(provider.get("provider_type", ""))
    base_url = str(provider.get("base_url", "")).strip()
    if provider_type == "ollama":
        probe_url = urljoin(base_url.rstrip("/") + "/", "api/tags") if base_url else "http://localhost:11434/api/tags"
    else:
        if not base_url:
            return {"status": "invalid", "ok": False, "message": "base_url is required"}
        probe_url = urljoin(base_url.rstrip("/") + "/", "models")

    ok, message = _http_json_probe(probe_url, secret)
    return {
        "status": "available" if ok else "unavailable",
        "ok": ok,
        "message": message,
        "checked_url": probe_url,
    }


def _normalize_routing(payload: dict[str, Any], providers: list[dict[str, Any]]) -> dict[str, Any]:
    provider_ids = {str(provider.get("id")) for provider in providers if isinstance(provider, dict)}
    out: dict[str, Any] = {}
    for purpose in ROUTING_PURPOSES:
        raw_rule = payload.get(purpose, {})
        if not isinstance(raw_rule, dict):
            raise HTTPException(status_code=400, detail=f"{purpose} routing rule must be an object")
        primary_id = str(raw_rule.get("primary_provider_id", "")).strip()
        fallback_ids = [str(item).strip() for item in raw_rule.get("fallback_provider_ids", []) if str(item).strip()]
        unknown = [item for item in [primary_id, *fallback_ids] if item and item not in provider_ids]
        if unknown:
            raise HTTPException(status_code=400, detail=f"unknown provider ids in {purpose}: {', '.join(unknown)}")
        deduped_fallbacks: list[str] = []
        for fallback_id in fallback_ids:
            if fallback_id == primary_id or fallback_id in deduped_fallbacks:
                continue
            deduped_fallbacks.append(fallback_id)
        out[purpose] = {
            "primary_provider_id": primary_id,
            "fallback_provider_ids": deduped_fallbacks,
            "allow_runtime_override": bool(raw_rule.get("allow_runtime_override", True)),
        }
    return out


def _normalize_ai_settings(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    tts = source.get("tts", {})
    if not isinstance(tts, dict):
        tts = {}
    engine = str(tts.get("engine", "kokoro_service") or "kokoro_service").strip()
    if engine not in {"browser", "kokoro_service"}:
        engine = "browser"
    rate = _bounded_float(tts.get("rate", 1.0), default=1.0, minimum=0.5, maximum=2.0)
    pitch = _bounded_float(tts.get("pitch", 1.0), default=1.0, minimum=0.0, maximum=2.0)
    speed = _bounded_float(tts.get("speed", 1.0), default=1.0, minimum=0.5, maximum=2.0)
    audio_format = str(tts.get("format", "wav") or "wav").strip().lower()
    if audio_format not in {"wav"}:
        audio_format = "wav"
    return {
        "tts": {
            "enabled": _bool_setting(tts.get("enabled", True), default=True),
            "engine": engine,
            "auto_read": _bool_setting(tts.get("auto_read", False), default=False),
            "service_url": str(tts.get("service_url", "http://127.0.0.1:9101") or "").strip() or "http://127.0.0.1:9101",
            "voice": str(tts.get("voice", "af_sky") or "").strip() or "af_sky",
            "format": audio_format,
            "speed": speed,
            "browser_fallback": _bool_setting(tts.get("browser_fallback", True), default=True),
            "voice_name": str(tts.get("voice_name", "") or "").strip(),
            "rate": rate,
            "pitch": pitch,
        },
        "ai_context_budget_chars": _bounded_int(
            source.get("ai_context_budget_chars", 24000),
            default=24000,
            minimum=4000,
            maximum=200000,
        ),
        "ai_use_planner_loop": _bool_setting(source.get("ai_use_planner_loop", False), default=False),
    }


def _bounded_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _bool_setting(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def _parse_int_field(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{name} must be an integer") from exc


def _default_routing(providers: list[dict[str, Any]]) -> dict[str, Any]:
    enabled_ids = [str(provider.get("id")) for provider in providers if isinstance(provider, dict) and provider.get("enabled", True)]
    first = enabled_ids[0] if enabled_ids else ""
    return {
        purpose: {
            "primary_provider_id": first,
            "fallback_provider_ids": enabled_ids[1:3],
            "allow_runtime_override": True,
        }
        for purpose in ROUTING_PURPOSES
    }


def _selected_sections(payload: dict[str, Any]) -> list[str]:
    raw_sections = payload.get("sections", [])
    if not isinstance(raw_sections, list):
        raise HTTPException(status_code=400, detail="sections must be a list")
    allowed = {"connectivity", "video", "appearance", "ai_settings", "llm_providers", "model_routing"}
    sections = []
    for raw_section in raw_sections:
        section = str(raw_section)
        if section in allowed and section not in sections:
            sections.append(section)
    if not sections:
        raise HTTPException(status_code=400, detail="at least one valid section is required")
    return sections


def _settings_export_payload(config, sections: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"schema_version": 1}
    if "connectivity" in sections:
        out["connectivity"] = _connectivity_payload(config)
    if "video" in sections:
        out["video"] = dict(config.video)
    if "appearance" in sections:
        out["appearance"] = dict(config.raw.get("appearance", {})) if isinstance(config.raw.get("appearance"), dict) else {}
    if "ai_settings" in sections:
        out["ai_settings"] = _normalize_ai_settings(config.raw.get("ai_settings", {}))
    if "llm_providers" in sections:
        providers = config.raw.get("llm_providers", [])
        out["llm_providers"] = [_provider_export(provider) for provider in providers if isinstance(provider, dict)]
    if "model_routing" in sections:
        out["model_routing"] = dict(config.raw.get("model_routing", {})) if isinstance(config.raw.get("model_routing"), dict) else {}
    return out


def _extract_section_payload(payload: dict[str, Any], section: str) -> Any:
    if section == "connectivity":
        if "connectivity" in payload and isinstance(payload["connectivity"], dict):
            return payload["connectivity"]
        if "mqtt" in payload:
            return {"mqtt": payload.get("mqtt"), "simulation": payload.get("simulation", {})}
        return None
    return payload.get(section)


def _apply_settings_sections(config, payload: dict[str, Any], sections: list[str]) -> list[str]:
    applied: list[str] = []
    if "connectivity" in sections:
        connectivity = _extract_section_payload(payload, "connectivity")
        if isinstance(connectivity, dict) and isinstance(connectivity.get("mqtt"), dict):
            config.raw["mqtt"] = dict(connectivity["mqtt"])
            simulation = connectivity.get("simulation", {})
            if isinstance(simulation, dict):
                config.raw.setdefault("simulation", {}).update(simulation)
            applied.append("connectivity")
    if "video" in sections:
        video = _extract_section_payload(payload, "video")
        if isinstance(video, dict):
            config.raw["video"] = dict(video)
            applied.append("video")
    if "appearance" in sections:
        appearance = _extract_section_payload(payload, "appearance")
        if isinstance(appearance, dict):
            config.raw["appearance"] = dict(appearance)
            applied.append("appearance")
    if "ai_settings" in sections:
        ai_settings = _extract_section_payload(payload, "ai_settings")
        if isinstance(ai_settings, dict):
            config.raw["ai_settings"] = _normalize_ai_settings(ai_settings)
            applied.append("ai_settings")
    if "llm_providers" in sections:
        providers_payload = _extract_section_payload(payload, "llm_providers")
        if isinstance(providers_payload, list):
            config.raw["llm_providers"] = [
                _normalize_provider(provider) for provider in providers_payload if isinstance(provider, dict)
            ]
            applied.append("llm_providers")
    if "model_routing" in sections:
        routing_payload = _extract_section_payload(payload, "model_routing")
        if isinstance(routing_payload, dict):
            providers = [provider for provider in config.raw.get("llm_providers", []) if isinstance(provider, dict)]
            config.raw["model_routing"] = _normalize_routing(routing_payload, providers)
            applied.append("model_routing")
    return applied


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


@app.get("/api/llm-providers")
async def get_llm_providers(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    providers = runtime.config.raw.setdefault("llm_providers", [])
    if not isinstance(providers, list):
        runtime.config.raw["llm_providers"] = []
        providers = runtime.config.raw["llm_providers"]
    return {"providers": [_provider_public(provider, runtime) for provider in providers if isinstance(provider, dict)]}


@app.post("/api/llm-providers")
async def create_llm_provider(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="provider payload must be an object")
    provider = _normalize_provider(payload)
    secret_value = str(payload.get("secret_value", "")).strip()
    if provider.get("auth_mode") == "stored_secret":
        if not secret_value:
            raise HTTPException(status_code=400, detail="secret_value is required for stored_secret auth")
        runtime.secret_store.set_secret(str(provider.get("secret_ref", "")), secret_value)
    providers = runtime.config.raw.setdefault("llm_providers", [])
    if not isinstance(providers, list):
        runtime.config.raw["llm_providers"] = []
        providers = runtime.config.raw["llm_providers"]
    providers.append(provider)
    save_config(runtime.config)
    evict_model_cache()
    return JSONResponse({"ok": True, "provider": _provider_public(provider, runtime)})


@app.put("/api/llm-providers/{provider_id}")
async def update_llm_provider(provider_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="provider payload must be an object")
    index, current = _find_provider(runtime, provider_id)
    provider = _normalize_provider(payload, current)
    provider["id"] = provider_id
    previous_auth_mode = str(current.get("auth_mode", "")).strip()
    previous_secret_ref = str(current.get("secret_ref", "")).strip()
    secret_value = str(payload.get("secret_value", "")).strip()
    if provider.get("auth_mode") == "stored_secret":
        if secret_value:
            runtime.secret_store.set_secret(str(provider.get("secret_ref", "")), secret_value)
        elif not runtime.secret_store.has_secret(str(provider.get("secret_ref", ""))):
            raise HTTPException(status_code=400, detail="secret_value is required for stored_secret auth")
    if previous_auth_mode == "stored_secret" and provider.get("auth_mode") != "stored_secret" and previous_secret_ref:
        runtime.secret_store.delete_secret(previous_secret_ref)
    runtime.config.raw["llm_providers"][index] = provider
    save_config(runtime.config)
    evict_model_cache()
    return JSONResponse({"ok": True, "provider": _provider_public(provider, runtime)})


@app.delete("/api/llm-providers/{provider_id}")
async def delete_llm_provider(provider_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    index, provider = _find_provider(runtime, provider_id)
    del runtime.config.raw["llm_providers"][index]
    if str(provider.get("auth_mode", "")).strip() == "stored_secret":
        runtime.secret_store.delete_secret(str(provider.get("secret_ref", "")).strip())

    routing = runtime.config.raw.get("model_routing")
    if isinstance(routing, dict):
        for rule in routing.values():
            if not isinstance(rule, dict):
                continue
            if rule.get("primary_provider_id") == provider_id:
                rule["primary_provider_id"] = ""
            fallback_ids = rule.get("fallback_provider_ids")
            if isinstance(fallback_ids, list):
                rule["fallback_provider_ids"] = [item for item in fallback_ids if item != provider_id]

    save_config(runtime.config)
    evict_model_cache()
    return JSONResponse({"ok": True, "deleted_provider_id": provider_id, "provider": _provider_public(provider, runtime)})


@app.post("/api/llm-providers/{provider_id}/check")
async def check_llm_provider(provider_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    index, provider = _find_provider(runtime, provider_id)
    loop = asyncio.get_running_loop()
    check = await loop.run_in_executor(None, _check_provider, runtime, provider)
    provider["last_check"] = check
    runtime.config.raw["llm_providers"][index] = provider
    save_config(runtime.config)
    return JSONResponse({"ok": check["ok"], "provider": _provider_public(provider, runtime), "check": check})


@app.post("/api/llm-providers/check-draft")
async def check_llm_provider_draft(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="provider payload must be an object")
    provider = _normalize_provider(payload)
    secret_value = str(payload.get("secret_value", "")).strip()
    draft_secret_override = None
    if provider.get("auth_mode") == "stored_secret":
        if not secret_value:
            return JSONResponse(
                {
                    "ok": False,
                    "provider": _provider_public(provider, runtime),
                    "check": {"status": "missing_key", "ok": False, "message": "stored API key is required for draft check"},
                }
            )
        draft_secret_override = secret_value
    loop = asyncio.get_running_loop()
    check = await loop.run_in_executor(None, _check_provider, runtime, provider, draft_secret_override)
    provider["last_check"] = check
    return JSONResponse({"ok": check["ok"], "provider": _provider_public(provider, runtime), "check": check})


@app.get("/api/model-routing")
async def get_model_routing(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    providers = [provider for provider in runtime.config.raw.setdefault("llm_providers", []) if isinstance(provider, dict)]
    current = runtime.config.raw.setdefault("model_routing", {})
    if not isinstance(current, dict) or not current:
        current = _default_routing(providers)
        runtime.config.raw["model_routing"] = current
    return {"purposes": ROUTING_PURPOSES, "routing": current}


@app.put("/api/model-routing")
async def set_model_routing(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    routing_payload = payload.get("routing") if isinstance(payload, dict) else None
    if not isinstance(routing_payload, dict):
        raise HTTPException(status_code=400, detail="routing object is required")
    providers = [provider for provider in runtime.config.raw.setdefault("llm_providers", []) if isinstance(provider, dict)]
    routing = _normalize_routing(routing_payload, providers)
    runtime.config.raw["model_routing"] = routing
    save_config(runtime.config)
    return JSONResponse({"ok": True, "purposes": ROUTING_PURPOSES, "routing": routing})


@app.get("/api/llm-settings")
async def get_llm_settings(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    providers = [provider for provider in runtime.config.raw.setdefault("llm_providers", []) if isinstance(provider, dict)]
    routing = runtime.config.raw.setdefault("model_routing", {})
    if not isinstance(routing, dict) or not routing:
        routing = _default_routing(providers)
        runtime.config.raw["model_routing"] = routing
    return {
        "providers": [_provider_public(provider, runtime) for provider in providers],
        "purposes": ROUTING_PURPOSES,
        "routing": routing,
    }


@app.put("/api/llm-settings")
async def set_llm_settings(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="settings payload must be an object")
    providers_payload = payload.get("llm_providers", payload.get("providers", []))
    if not isinstance(providers_payload, list):
        raise HTTPException(status_code=400, detail="llm_providers must be a list")
    providers = [_normalize_provider(provider) for provider in providers_payload if isinstance(provider, dict)]
    routing_payload = payload.get("model_routing", payload.get("routing", {}))
    if not isinstance(routing_payload, dict):
        raise HTTPException(status_code=400, detail="model_routing must be an object")
    runtime.config.raw["llm_providers"] = providers
    runtime.config.raw["model_routing"] = _normalize_routing(routing_payload, providers) if routing_payload else _default_routing(providers)
    save_config(runtime.config)
    return JSONResponse({
        "ok": True,
        "providers": [_provider_public(provider, runtime) for provider in providers],
        "routing": runtime.config.raw["model_routing"],
    })


def _public_ai_session(session: dict[str, Any], include_messages: bool = False) -> dict[str, Any]:
    out = dict(session)
    if not include_messages:
        out.pop("messages", None)
    out["source_controls"] = normalize_source_controls(out.get("source_controls"))
    return out


def _tool_permission_label(value: Any) -> str:
    labels = {
        "read_only": "read-only",
        "analysis": "analysis",
        "planning": "planning",
        "command_staging": "command staging",
        "execution": "execution",
    }
    key = str(value or "").strip().lower()
    return labels.get(key, key or "unknown")


def _format_retrieval_surfaces_markdown(
    session_id: str,
    source_controls: dict[str, bool],
) -> str:
    retrieval_request = normalize_retrieval_request({"source_controls": source_controls}, session_id=session_id)
    sources = build_retrieved_sources(retrieval_request=retrieval_request, session_id=session_id)
    enabled_sources = [source for source in sources if source_controls.get(str(source.get("source", "")))]
    disabled_keys = [key for key, enabled in source_controls.items() if not enabled]

    lines = ["## Retrieval Surfaces", ""]
    if enabled_sources:
        lines.append("Enabled for this session:")
        for source in enabled_sources:
            label = str(source.get("source", "source")).replace("_", " ")
            status = str(source.get("status", "planned"))
            note = str(source.get("note", "")).strip()
            lines.append(f"- `{label}`: {status}")
            if note:
                lines.append(f"  {note}")
    else:
        lines.append("No retrieval surfaces are enabled for this session.")

    if disabled_keys:
        lines.extend(["", "Disabled for this session:"])
        for key in disabled_keys:
            lines.append(f"- `{key.replace('_', ' ')}`")
    return "\n".join(lines).strip()


def _format_tool_catalog_markdown_brief(
    tool_registry: ToolRegistry,
    *,
    source_controls: dict[str, Any] | None = None,
) -> str:
    allowed_tool_names = allowed_tool_names_for_source_controls(source_controls)
    definitions = [definition for definition in tool_registry.definitions() if definition.name in allowed_tool_names]
    count = len(definitions)
    noun = "tool" if count == 1 else "tools"
    lines = ["## Agent Tools", "", f"{count} {noun} available in agent mode.", ""]
    for definition in definitions:
        lines.append(f"- **`{definition.name}`**: {definition.description}")
    return "\n".join(lines).strip()


def _format_tool_catalog_markdown_full(
    tool_registry: ToolRegistry,
    *,
    source_controls: dict[str, Any] | None = None,
) -> str:
    allowed_tool_names = allowed_tool_names_for_source_controls(source_controls)
    definitions = [definition for definition in tool_registry.definitions() if definition.name in allowed_tool_names]
    lines = ["## Agent Tools", ""]
    count = len(definitions)
    noun = "tool" if count == 1 else "tools"
    lines.append(f"{count} {noun} available in agent mode.")
    for definition in definitions:
        permission = _tool_permission_label(definition.permission)
        lines.extend([
            "",
            f"### `{definition.name}`",
            f"- Permission: `{permission}`",
            f"- Tier: `{definition.tier}`",
            f"- Description: {definition.description}",
        ])
        contract = definition.contract if isinstance(definition.contract, dict) else {}
        inputs = contract.get("inputs")
        required = contract.get("required_inputs")
        upstream = contract.get("upstream_from_tools")
        returns = contract.get("returns")
        downstream = contract.get("next_tools")
        if isinstance(inputs, dict) and inputs:
            lines.append(f"- Inputs: {_format_contract_mapping(inputs)}")
        if isinstance(required, list) and required:
            lines.append(f"- Required inputs: `{', '.join(str(item) for item in required)}`")
        if definition.required_scopes:
            lines.append(f"- Required scopes: `{', '.join(sorted(definition.required_scopes))}`")
        if definition.side_effects:
            lines.append(f"- Side effects: `{', '.join(sorted(definition.side_effects))}`")
        if isinstance(upstream, list) and upstream:
            lines.append(f"- Upstream sources: `{', '.join(str(item) for item in upstream)}`")
        if isinstance(returns, dict) and returns:
            lines.append(f"- Returns: {_format_contract_mapping(returns)}")
        if isinstance(downstream, list) and downstream:
            lines.append(f"- Next tools: `{', '.join(str(item) for item in downstream)}`")
    return "\n".join(lines).strip()


def _format_contract_mapping(values: dict[str, Any]) -> str:
    return ", ".join(f"`{key}`: `{value}`" for key, value in values.items())


def _format_agent_tool_activity_markdown(session: dict[str, Any]) -> str:
    messages = session.get("messages")
    if not isinstance(messages, list):
        return "## Agent Tool Activity\n\nNo message history is available for this session."
    for message in reversed(messages):
        if str(message.get("role", "")) != "assistant":
            continue
        meta = message.get("meta")
        if not isinstance(meta, dict):
            continue
        tool_calls = meta.get("agent_tool_progress")
        if not isinstance(tool_calls, list) or not tool_calls:
            tool_calls = meta.get("tool_calls")
        if not isinstance(tool_calls, list) or not tool_calls:
            continue
        lines = ["## Agent Tool Activity", ""]
        created_at = message.get("created_at")
        if created_at is not None:
            lines.append(f"Latest assistant message: `{created_at}`")
            lines.append("")
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            name = str(call.get("name") or call.get("tool") or "tool")
            status = str(call.get("status") or ("complete" if call.get("result") is not None else "recorded"))
            lines.append(f"- `{name}`: {status}")
        return "\n".join(lines).strip()
    return "## Agent Tool Activity\n\nNo agent tool activity has been recorded in this session yet."


def _build_ai_session_command_response(
    runtime: AppRuntime,
    tool_registry: ToolRegistry,
    session_id: str,
    command: str,
) -> tuple[str, str]:
    include_messages = str(command or "").strip().lower() == "tool-activity"
    session = runtime.ai_store.get_session(session_id, include_messages=include_messages)
    if session is None:
        raise KeyError("AI session not found")
    source_controls = normalize_source_controls(session.get("source_controls"))
    normalized = str(command or "").strip().lower()
    if normalized == "retrieval-surfaces":
        return "/retrieval-surfaces", _format_retrieval_surfaces_markdown(session_id, source_controls)
    if normalized == "tool-activity":
        return "/tool-activity", _format_agent_tool_activity_markdown(session)
    if normalized == "capabilities brief":
        retrieval = _format_retrieval_surfaces_markdown(session_id, source_controls)
        tools = _format_tool_catalog_markdown_brief(tool_registry, source_controls=source_controls)
        return "/capabilities brief", f"{retrieval}\n\n{tools}"
    if normalized == "capabilities full":
        retrieval = _format_retrieval_surfaces_markdown(session_id, source_controls)
        tools = _format_tool_catalog_markdown_full(tool_registry, source_controls=source_controls)
        return "/capabilities full", f"{retrieval}\n\n{tools}"
    raise ValueError(f"unsupported command '{command}'")


def _ai_chat_service(request: Request) -> AIChatService:
    return request.app.state.ai_chat_service


def _tool_registry(request: Request) -> ToolRegistry:
    wb_runtime: WorkbenchGraphRuntime = request.app.state.workbench_runtime
    return wb_runtime.tool_registry


def _agent_trace_store(request: Request) -> AgentTraceStore:
    return request.app.state.agent_trace_store


def _request_timezone_name(request: Request, payload: dict[str, Any] | None = None) -> str:
    if isinstance(payload, dict):
        clean = str(payload.get("timezone", "")).strip()
        if clean:
            return clean
    return str(request.headers.get("x-operator-timezone", "")).strip()


async def _ai_context_snapshot(
    runtime: AppRuntime,
    tool_registry: ToolRegistry,
    user_message: str = "",
    session_id: str = "",
    timezone_name: str = "",
    run_mode: str = "chat",
) -> dict[str, Any]:
    session = runtime.ai_store.get_session(session_id, include_messages=False) if session_id else None
    source_controls = normalize_source_controls((session or {}).get("source_controls"))
    snapshot = await AIContextService(runtime).build_compact_context(
        user_message,
        session_id=session_id,
        timezone_name=timezone_name,
        run_mode=run_mode,
        source_controls=source_controls,
    )
    full_ctx = snapshot.meta.get("context_snapshot") if isinstance(snapshot.meta, dict) else {}
    details = (full_ctx or {}).get("details") if isinstance(full_ctx, dict) else {}
    replay_summary = details.get("current_replay") if isinstance(details, dict) else {}
    chat_history_summary = details.get("ai_chat_history") if isinstance(details, dict) else {}
    settings_summary = (full_ctx or {}).get("settings") if isinstance(full_ctx, dict) else {}
    rover_state = (full_ctx or {}).get("rover") if isinstance(full_ctx, dict) else {}
    runtime_summary = (full_ctx or {}).get("runtime") if isinstance(full_ctx, dict) else {}
    retrieval_request = normalize_retrieval_request(
        {"source_controls": source_controls},
        user_prompt=user_message,
        session_id=session_id,
    )
    sensor_summary = {
        "telemetry_fresh": (rover_state or {}).get("telemetry_fresh"),
        "camera_fresh": (rover_state or {}).get("camera_fresh"),
        "video_delivery": (runtime_summary or {}).get("video"),
    }
    retrieved_sources = build_retrieved_sources(
        retrieval_request=retrieval_request,
        session_id=session_id,
        replay_summary=replay_summary if isinstance(replay_summary, dict) else {},
        chat_history_summary=chat_history_summary if isinstance(chat_history_summary, dict) else {},
        settings_summary=settings_summary if isinstance(settings_summary, dict) else {},
        sensor_summary=sensor_summary,
    )
    loaded_data_refs = build_loaded_data_refs(
        retrieval_request=retrieval_request,
        session_id=session_id,
        replay_summary=replay_summary if isinstance(replay_summary, dict) else {},
        chat_history_summary=chat_history_summary if isinstance(chat_history_summary, dict) else {},
        settings_summary=settings_summary if isinstance(settings_summary, dict) else {},
        sensor_summary=sensor_summary,
    )
    meta = dict(snapshot.meta)
    meta["retrieval_request"] = retrieval_request
    meta["retrieved_sources"] = retrieved_sources
    meta["loaded_data_refs"] = loaded_data_refs
    meta["retrieval_citations"] = build_retrieval_citations(retrieved_sources, loaded_data_refs)
    meta["data_access_manifest"] = build_data_access_manifest(
        tool_registry.definitions(),
        allowed_tool_names=allowed_tool_names_for_source_controls(source_controls),
    )
    return {"prompt": snapshot.prompt, "meta": meta}


def _latest_user_content(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _latest_user_run_mode(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        meta = message.get("meta")
        if not isinstance(meta, dict):
            return "chat"
        clean = str(meta.get("run_mode") or "chat").strip().lower()
        return "agent" if clean == "agent" else "chat"
    return "chat"


def _ai_run_mode(payload: dict[str, Any]) -> str:
    clean = str(payload.get("run_mode", "chat")).strip().lower()
    if clean in {"", "chat", "general_chat", "workbench", "intent", "rover_intent_test"}:
        return "chat"
    if clean == "agent":
        return "agent"
    raise HTTPException(status_code=400, detail="run_mode must be chat or agent")


async def _run_ai_call(runtime: AppRuntime, func, *args) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(runtime.ai_executor, func, *args)


def _llm_provider_http_exception(exc: Exception) -> HTTPException | None:
    try:
        import httpx
    except ImportError:
        httpx = None

    if httpx is not None:
        if isinstance(exc, httpx.TimeoutException):
            return HTTPException(status_code=504, detail="LLM provider request timed out.")
        if isinstance(exc, httpx.ConnectError):
            return HTTPException(status_code=503, detail="Could not connect to the LLM provider.")
        if isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code
            if status_code == 404:
                return HTTPException(status_code=400, detail="LLM provider model or endpoint was not found. Check the model ID and base URL.")
            if status_code == 429:
                return HTTPException(status_code=429, detail="LLM provider rate limit or quota was reached.")
            return HTTPException(status_code=502, detail=f"LLM provider request failed with HTTP {status_code}.")

    try:
        import ollama
    except ImportError:
        ollama = None

    if ollama is not None:
        response_error = getattr(ollama, "ResponseError", None)
        if response_error and isinstance(exc, response_error):
            status_code = int(getattr(exc, "status_code", 0) or 0)
            message = str(getattr(exc, "error", "") or exc).strip() or "Ollama request failed."
            if status_code == 404:
                return HTTPException(status_code=400, detail=f"Ollama model was not found. Pull the model or check model_id. {message}")
            return HTTPException(status_code=502, detail=message)

    try:
        import openai
    except ImportError:
        return None

    authentication_error = getattr(openai, "AuthenticationError", None)
    permission_denied_error = getattr(openai, "PermissionDeniedError", None)
    not_found_error = getattr(openai, "NotFoundError", None)
    bad_request_error = getattr(openai, "BadRequestError", None)
    rate_limit_error = getattr(openai, "RateLimitError", None)
    timeout_error = getattr(openai, "APITimeoutError", None)
    connection_error = getattr(openai, "APIConnectionError", None)
    status_error = getattr(openai, "APIStatusError", None)

    if authentication_error and isinstance(exc, authentication_error):
        return HTTPException(
            status_code=400,
            detail="LLM provider authentication failed. Check the configured API key.",
        )
    if permission_denied_error and isinstance(exc, permission_denied_error):
        return HTTPException(
            status_code=400,
            detail="LLM provider permission denied. Check API key access for this model.",
        )
    if not_found_error and isinstance(exc, not_found_error):
        return HTTPException(
            status_code=400,
            detail="LLM provider model or endpoint was not found. Check the model ID and base URL.",
        )
    if bad_request_error and isinstance(exc, bad_request_error):
        return HTTPException(
            status_code=400,
            detail=_llm_provider_error_detail(exc, "LLM provider rejected the request."),
        )
    if rate_limit_error and isinstance(exc, rate_limit_error):
        return HTTPException(status_code=429, detail="LLM provider rate limit or quota was reached.")
    if timeout_error and isinstance(exc, timeout_error):
        return HTTPException(status_code=504, detail="LLM provider request timed out.")
    if connection_error and isinstance(exc, connection_error):
        return HTTPException(status_code=503, detail="Could not connect to the LLM provider.")
    if status_error and isinstance(exc, status_error):
        return HTTPException(
            status_code=502,
            detail=_llm_provider_error_detail(exc, "LLM provider request failed."),
        )
    return None


def _llm_provider_error_detail(exc: Exception, fallback: str) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        for key in ("detail", "message", "error"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return _redact_secret_text(value.strip())
            if isinstance(value, dict) and isinstance(value.get("message"), str):
                return _redact_secret_text(value["message"].strip())
    return _redact_secret_text(fallback)


def _ai_stream_error_line(detail: str) -> str:
    return f"{json.dumps({'type': 'error', 'detail': detail}, separators=(',', ':'))}\n"


def _llm_stream_error_detail(exc: Exception) -> str:
    provider_error = _llm_provider_http_exception(exc)
    if provider_error is not None:
        return str(provider_error.detail)
    return str(exc) or "Chat streaming failed."


def _stream_ai_events(stream: Any) -> Any:
    try:
        yield from stream
    except (KeyError, ValueError, RuntimeError) as exc:
        yield _ai_stream_error_line(str(exc))
    except Exception as exc:
        yield _ai_stream_error_line(_llm_stream_error_detail(exc))


@app.get("/api/ai/sessions")
async def list_ai_sessions(
    request: Request,
    include_archived: bool = False,
    archived_only: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    runtime = _runtime(request)
    sessions = runtime.ai_store.list_sessions(
        limit=limit,
        include_archived=include_archived,
        archived_only=archived_only,
    )
    return {"sessions": [_public_ai_session(session) for session in sessions]}


@app.post("/api/ai/sessions")
async def create_ai_session(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="session payload must be an object")
    session = runtime.ai_store.create_session(
        title=str(payload.get("title", "New chat")),
        mode=str(payload.get("mode", "general_chat")),
        provider_id=str(payload.get("provider_id", "")),
        source_controls=payload.get("source_controls"),
    )
    return JSONResponse({"ok": True, "session": _public_ai_session(session)})


@app.get("/api/ai/sessions/{session_id}")
async def get_ai_session(session_id: str, request: Request, include_archived: bool = False) -> dict[str, Any]:
    runtime = _runtime(request)
    session = runtime.ai_store.get_session(session_id, include_messages=True)
    if session is None:
        raise HTTPException(status_code=404, detail="AI session not found")
    if session.get("archived_at") is not None and not include_archived:
        raise HTTPException(status_code=404, detail="AI session not found")
    return {"session": _public_ai_session(session, include_messages=True)}


@app.post("/api/ai/sessions/{session_id}/commands")
async def run_ai_session_command(session_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="command payload must be an object")
    try:
        raw_command, assistant_content = _build_ai_session_command_response(
            runtime,
            _tool_registry(request),
            session_id,
            str(payload.get("command", "")),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user_message = runtime.ai_store.add_message(
        session_id,
        role="user",
        content=raw_command,
        meta={"run_mode": "chat", "local_command": raw_command},
    )
    assistant_message = runtime.ai_store.add_message(
        session_id,
        role="assistant",
        content=assistant_content,
        meta={"run_mode": "chat", "local_command": raw_command},
    )
    return JSONResponse({
        "ok": True,
        "user_message": user_message,
        "assistant_message": assistant_message,
    })


@app.patch("/api/ai/sessions/{session_id}")
async def update_ai_session(session_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="session payload must be an object")
    session = runtime.ai_store.update_session(
        session_id,
        title=str(payload["title"]) if "title" in payload else None,
        provider_id=str(payload["provider_id"]) if "provider_id" in payload else None,
        mode=str(payload["mode"]) if "mode" in payload else None,
        source_controls=payload["source_controls"] if "source_controls" in payload else None,
    )
    if session is None:
        raise HTTPException(status_code=404, detail="AI session not found")
    return JSONResponse({"ok": True, "session": _public_ai_session(session)})


@app.delete("/api/ai/sessions/{session_id}")
async def archive_ai_session(session_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    if not runtime.ai_store.archive_session(session_id):
        raise HTTPException(status_code=404, detail="AI session not found")
    return JSONResponse({"ok": True, "archived_session_id": session_id})


@app.post("/api/ai/sessions/{session_id}/restore")
async def restore_ai_session(session_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    if not runtime.ai_store.restore_session(session_id):
        raise HTTPException(status_code=404, detail="AI session not found")
    session = runtime.ai_store.get_session(session_id, include_messages=False)
    return JSONResponse({"ok": True, "session": _public_ai_session(session or {})})


@app.delete("/api/ai/sessions/{session_id}/purge")
async def purge_ai_session(session_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    if not runtime.ai_store.purge_session(session_id):
        raise HTTPException(status_code=404, detail="AI session not found")
    return JSONResponse({"ok": True, "deleted_session_id": session_id})


@app.post("/api/ai/sessions/{session_id}/messages")
async def send_ai_message(session_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="message payload must be an object")
    content = str(payload.get("content", ""))
    run_mode = _ai_run_mode(payload)
    timezone_name = _request_timezone_name(request, payload)
    try:
        context_snapshot = await _ai_context_snapshot(
            runtime,
            _tool_registry(request),
            content,
            session_id=session_id,
            timezone_name=timezone_name,
            run_mode=run_mode,
        )
        result = await _run_ai_call(
            runtime,
            _ai_chat_service(request).send_message,
            runtime.config,
            session_id,
            content,
            context_snapshot,
            run_mode,
            {"timezone_name": timezone_name, "runtime": runtime},
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        provider_error = _llm_provider_http_exception(exc)
        if provider_error is not None:
            raise provider_error from exc
        raise
    return JSONResponse({"ok": True, **result})


@app.post("/api/ai/sessions/{session_id}/messages/stream")
async def send_ai_message_stream(session_id: str, request: Request) -> StreamingResponse:
    inflight = _ai_inflight_streams(request)
    resume = request.query_params.get("resume", "").strip().lower() in {"1", "true", "yes"}
    if resume:
        run = inflight.get(session_id)
        if run is None:
            raise HTTPException(status_code=404, detail="No in-progress response for this session.")
        return StreamingResponse(run.stream(), media_type="application/x-ndjson")

    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="message payload must be an object")
    content = str(payload.get("content", ""))
    run_mode = _ai_run_mode(payload)
    timezone_name = _request_timezone_name(request, payload)
    try:
        context_snapshot = await _ai_context_snapshot(
            runtime,
            _tool_registry(request),
            content,
            session_id=session_id,
            timezone_name=timezone_name,
            run_mode=run_mode,
        )
        def _stream_factory() -> Any:
            return _ai_chat_service(request).stream_message_events(
                runtime.config,
                session_id,
                content,
                context_snapshot,
                run_mode,
                {"timezone_name": timezone_name, "runtime": runtime},
            )
        run = inflight.start(runtime, session_id, _stream_factory)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        provider_error = _llm_provider_http_exception(exc)
        if provider_error is not None:
            raise provider_error from exc
        raise
    return StreamingResponse(run.stream(), media_type="application/x-ndjson")


@app.post("/api/ai/sessions/{session_id}/retry")
async def retry_ai_message(session_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        payload = {}
    timezone_name = _request_timezone_name(request, payload)
    try:
        messages = runtime.ai_store.latest_messages(session_id, limit=AI_CONTEXT_MESSAGE_LIMIT)
        context_snapshot = await _ai_context_snapshot(
            runtime,
            _tool_registry(request),
            _latest_user_content(messages),
            session_id=session_id,
            timezone_name=timezone_name,
            run_mode=_latest_user_run_mode(messages),
        )
        result = await _run_ai_call(
            runtime,
            _ai_chat_service(request).retry_last_response,
            runtime.config,
            session_id,
            context_snapshot,
            {"timezone_name": timezone_name, "runtime": runtime},
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        provider_error = _llm_provider_http_exception(exc)
        if provider_error is not None:
            raise provider_error from exc
        raise
    return JSONResponse({"ok": True, **result})


@app.post("/api/ai/sessions/{session_id}/retry/stream")
async def retry_ai_message_stream(session_id: str, request: Request) -> StreamingResponse:
    inflight = _ai_inflight_streams(request)
    resume = request.query_params.get("resume", "").strip().lower() in {"1", "true", "yes"}
    if resume:
        run = inflight.get(session_id)
        if run is None:
            raise HTTPException(status_code=404, detail="No in-progress response for this session.")
        return StreamingResponse(run.stream(), media_type="application/x-ndjson")

    runtime = _runtime(request)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        payload = {}
    timezone_name = _request_timezone_name(request, payload)
    try:
        messages = runtime.ai_store.latest_messages(session_id, limit=AI_CONTEXT_MESSAGE_LIMIT)
        context_snapshot = await _ai_context_snapshot(
            runtime,
            _tool_registry(request),
            _latest_user_content(messages),
            session_id=session_id,
            timezone_name=timezone_name,
            run_mode=_latest_user_run_mode(messages),
        )
        def _stream_factory() -> Any:
            return _ai_chat_service(request).stream_retry_events(
                runtime.config,
                session_id,
                context_snapshot,
                {"timezone_name": timezone_name, "runtime": runtime},
            )
        run = inflight.start(runtime, session_id, _stream_factory)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        provider_error = _llm_provider_http_exception(exc)
        if provider_error is not None:
            raise provider_error from exc
        raise
    return StreamingResponse(run.stream(), media_type="application/x-ndjson")


@app.get("/api/ai/sessions/{session_id}/stream-status")
async def ai_session_stream_status(session_id: str, request: Request) -> dict[str, Any]:
    session = _runtime(request).ai_store.get_session(session_id, include_messages=False)
    if session is None or session.get("archived_at") is not None:
        raise HTTPException(status_code=404, detail="AI session not found")
    run = _ai_inflight_streams(request).get(session_id)
    return {"session_id": session_id, "in_progress": bool(run), "run_id": run.run_id if run else ""}


@app.get("/api/ai/traces")
async def list_ai_traces(request: Request, limit: int = 20, day: str = "") -> JSONResponse:
    trace_store = _agent_trace_store(request)
    clean_day = str(day or "").strip()
    if clean_day and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", clean_day):
        raise HTTPException(status_code=400, detail="day must use YYYY-MM-DD format")
    traces = trace_store.list(limit=max(1, min(200, limit)), day=clean_day)
    return JSONResponse({"ok": True, "traces": traces, "count": len(traces)})


@app.get("/api/ai/traces/{trace_id}")
async def get_ai_trace(trace_id: str, request: Request) -> JSONResponse:
    trace_store = _agent_trace_store(request)
    try:
        trace = trace_store.get(trace_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="agent trace not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return JSONResponse({"ok": True, "trace": trace})


@app.post("/api/ai/sessions/{session_id}/intent-test")
async def rover_intent_test(session_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")
    content = str(payload.get("content", "")).strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    timezone_name = _request_timezone_name(request, payload)

    session = runtime.ai_store.get_session(session_id, include_messages=False)
    if session is None or session.get("archived_at") is not None:
        raise HTTPException(status_code=404, detail="AI session not found")

    try:
        resolved = resolve_intent_provider(
            runtime.config,
            provider_id=str(session.get("provider_id") or ""),
            secret_resolver=runtime.secret_store.get_secret,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    context_snapshot = await _ai_context_snapshot(
        runtime,
        _tool_registry(request),
        content,
        session_id=session_id,
        timezone_name=timezone_name,
        run_mode="rover_intent_test",
    )
    context_summary = str(context_snapshot.get("prompt") or "")

    intent_service = IntentService()
    loop = asyncio.get_event_loop()
    try:
        parse_result = await loop.run_in_executor(
            None,
            lambda: intent_service.parse(
                content,
                model=resolved.model,
                context_summary=context_summary,
                timezone_name=timezone_name,
            ),
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        provider_error = _llm_provider_http_exception(exc)
        if provider_error is not None:
            raise provider_error from exc
        raise

    intent = parse_result["intent"]
    errors = parse_result.get("parse_errors") or []
    tool_calls: list[dict[str, Any]] = []
    target_resolution: dict[str, Any] = {}

    target = intent.get("target") or {}
    if intent.get("requires_rover_motion") and any(v is not None and v != "" for v in target.values()):
        registry = ToolRegistry()
        target_resolution = registry.invoke(
            "resolve_spatial_target",
            {"target": target},
            runtime,
            context_snapshot,
            timezone_name=timezone_name,
        )
        tool_calls.append({
            "tool": "resolve_spatial_target",
            "args": {"target": target},
            "result": target_resolution,
        })

    runtime.ai_store.maybe_auto_title(session_id, content)
    user_message = runtime.ai_store.add_message(
        session_id,
        role="user",
        content=content,
        provider_id=str(resolved.provider.get("id", "")),
        model_id=str(resolved.provider.get("model_id", "")),
        meta={"run_mode": "rover_intent_test"},
    )

    intent_type = str(intent.get("intent_type", "unknown"))
    summary = str(intent.get("summary", ""))
    approval_note = " Operator approval required before any rover motion." if intent.get("requires_rover_motion") else ""
    errors_note = f"\n\nParse errors: {', '.join(errors)}" if errors else ""
    assistant_content = f"**Intent parsed:** {intent_type}\n{summary}{approval_note}{errors_note}"

    assistant_message = runtime.ai_store.add_message(
        session_id,
        role="assistant",
        content=assistant_content,
        provider_id=str(resolved.provider.get("id", "")),
        model_id=str(resolved.provider.get("model_id", "")),
        latency_ms=parse_result.get("latency_ms", 0),
        meta={
            "run_mode": "rover_intent_test",
            "intent": intent,
            "target_resolution": target_resolution,
            "parse_errors": errors,
            "tool_calls": tool_calls,
        },
    )

    return JSONResponse({
        "ok": True,
        "intent": intent,
        "target_resolution": target_resolution,
        "parse_errors": errors,
        "tool_calls": tool_calls,
        "user_message": user_message,
        "assistant_message": assistant_message,
        "session": _public_ai_session(session),
    })


@app.post("/api/ai/sessions/{session_id}/mission-draft")
async def create_mission_draft(session_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")

    session = runtime.ai_store.get_session(session_id, include_messages=False)
    if session is None or session.get("archived_at") is not None:
        raise HTTPException(status_code=404, detail="AI session not found")

    intent = payload.get("intent")
    if not isinstance(intent, dict):
        raise HTTPException(status_code=400, detail="intent is required and must be an object")
    target_resolution = payload.get("target_resolution") or {}
    if not isinstance(target_resolution, dict):
        raise HTTPException(status_code=400, detail="target_resolution must be an object")
    draft_payload = payload.get("draft")
    if not isinstance(draft_payload, dict):
        raise HTTPException(status_code=400, detail="draft is required and must be an object")
    source_message_id = str(payload.get("source_message_id") or "")

    context_snapshot = payload.get("context_snapshot") or {}
    rover_state: dict[str, Any] | None = None
    if isinstance(context_snapshot, dict):
        meta = context_snapshot.get("meta") or {}
        snap = meta.get("context_snapshot") if isinstance(meta, dict) else None
        rover_state = snap.get("rover") if isinstance(snap, dict) else None

    draft = runtime.mission_draft_service.create_draft(
        session_id=session_id,
        source_message_id=source_message_id,
        intent=intent,
        target_resolution=target_resolution,
        draft_payload=draft_payload,
        rover_state=rover_state if isinstance(rover_state, dict) else None,
    )
    return JSONResponse({"ok": True, "draft": draft})


@app.get("/api/ai/mission-drafts")
async def list_mission_drafts(
    request: Request,
    session_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> JSONResponse:
    runtime = _runtime(request)
    drafts = runtime.mission_draft_service.list_drafts(
        session_id=session_id,
        status_filter=status,
        limit=max(1, min(200, limit)),
    )
    return JSONResponse({"ok": True, "drafts": drafts, "count": len(drafts)})


@app.get("/api/ai/mission-drafts/{draft_id}")
async def get_mission_draft(draft_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    draft = runtime.mission_draft_service.get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="mission draft not found")
    return JSONResponse({"ok": True, "draft": draft})


@app.post("/api/ai/mission-drafts/{draft_id}/approve")
async def approve_mission_draft(draft_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    note = str(payload.get("note", "") if isinstance(payload, dict) else "")
    draft = runtime.mission_draft_service.approve_draft(draft_id, note=note)
    if draft is None:
        raise HTTPException(
            status_code=409,
            detail="draft not found or not in awaiting_approval status",
        )
    return JSONResponse({"ok": True, "draft": draft})


@app.post("/api/ai/mission-drafts/{draft_id}/reject")
async def reject_mission_draft(draft_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    note = str(payload.get("note", "") if isinstance(payload, dict) else "")
    draft = runtime.mission_draft_service.reject_draft(draft_id, note=note)
    if draft is None:
        raise HTTPException(
            status_code=409,
            detail="draft not found or not in a rejectable status",
        )
    return JSONResponse({"ok": True, "draft": draft})


@app.post("/api/ai/sessions/{session_id}/workbench/stream")
async def run_workbench_session_stream(session_id: str, request: Request) -> StreamingResponse:
    """Stream a workbench planning graph run for the given session.

    Request body:
        content        (str, required)  — the operator's planning prompt
        operator_timezone (str, optional) — IANA timezone name

    Response: NDJSON stream of graph lifecycle and tool events:
        graph_run_start, graph_node_result, agent_tool_start, agent_tool_result,
        mission_draft_created, mission_draft_validation, mission_draft_approval_required,
        graph_run_end, graph_run_error
    """
    runtime = _runtime(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="request body must be JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")

    content = str(payload.get("content", "")).strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")

    timezone_name = _request_timezone_name(request, payload)
    wb_runtime: WorkbenchGraphRuntime = request.app.state.workbench_runtime

    session = runtime.ai_store.get_session(session_id, include_messages=False)
    if session is None or session.get("archived_at") is not None:
        raise HTTPException(status_code=404, detail="AI session not found")

    async def _generate():
        try:
            async for line in stream_workbench_graph(
                wb_runtime,
                session_id=session_id,
                user_prompt=content,
                operator_timezone=timezone_name,
                session_mode=str(session.get("mode", "workbench")),
                source_controls=session.get("source_controls"),
            ):
                yield line
        except Exception as exc:
            yield _ai_stream_error_line(str(exc))

    return StreamingResponse(_generate(), media_type="application/x-ndjson")


@app.post("/api/ai/sessions/{session_id}/workbench/thread/{thread_id}/resume")
async def resume_workbench_session(
    session_id: str, thread_id: str, request: Request
) -> StreamingResponse:
    """Resume a workbench graph suspended at an interrupt() approval gate.

    Request body:
        decision  (str, required)   — "approve", "reject", "continue", or "cancel"
        note      (str, optional)   — operator note attached to the approval/rejection/clarification

    Response: NDJSON stream continuing from the interrupted node:
        graph_resume_start, graph_node_result, mission_draft_decision, graph_run_end
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="request body must be JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")

    decision = str(payload.get("decision", "")).strip().lower()
    if decision not in ("approve", "reject", "continue", "cancel"):
        raise HTTPException(status_code=400, detail="decision must be 'approve', 'reject', 'continue', or 'cancel'")
    note = str(payload.get("note", "") or "")

    session = _runtime(request).ai_store.get_session(session_id, include_messages=False)
    if session is None or session.get("archived_at") is not None:
        raise HTTPException(status_code=404, detail="AI session not found")

    wb_runtime: WorkbenchGraphRuntime = request.app.state.workbench_runtime

    async def _generate():
        try:
            async for line in resume_workbench_graph(
                wb_runtime,
                thread_id=thread_id,
                decision=decision,
                note=note,
            ):
                yield line
        except Exception as exc:
            yield _ai_stream_error_line(str(exc))

    return StreamingResponse(_generate(), media_type="application/x-ndjson")


@app.post("/api/settings/export")
async def export_settings_sections(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="export payload must be an object")
    sections = _selected_sections(payload)
    return JSONResponse(_settings_export_payload(runtime.config, sections))


@app.post("/api/settings/load-from-path")
async def load_settings_sections_from_path(request: Request) -> JSONResponse:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="load payload must be an object")
    sections = _selected_sections(payload)
    resolved_path = _resolve_backend_config_path(str(payload.get("path", "")))
    if not resolved_path.exists():
        raise HTTPException(status_code=404, detail="config file not found")
    data = _load_existing_json_dict(resolved_path)
    found = [section for section in sections if _extract_section_payload(data, section) is not None]
    missing = [section for section in sections if section not in found]
    selected_payload = {"schema_version": data.get("schema_version", 1)}
    for section in found:
        selected_payload[section] = _extract_section_payload(data, section)
    return JSONResponse({
        "ok": True,
        "resolved_path": str(resolved_path),
        "found_sections": found,
        "missing_sections": missing,
        "settings": selected_payload,
    })


@app.post("/api/settings/save-to-path")
async def save_settings_sections_to_path(request: Request) -> JSONResponse:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="save payload must be an object")
    sections = _selected_sections(payload)
    resolved_path = _resolve_backend_config_path(str(payload.get("path", "")))
    settings_payload = payload.get("settings")
    if not isinstance(settings_payload, dict):
        raise HTTPException(status_code=400, detail="settings object is required")
    existing = _load_existing_json_dict(resolved_path)
    merged = dict(existing)
    for section in sections:
        section_payload = _extract_section_payload(settings_payload, section)
        if section_payload is None:
            continue
        if section == "connectivity":
            if isinstance(section_payload, dict) and isinstance(section_payload.get("mqtt"), dict):
                merged["mqtt"] = section_payload["mqtt"]
                if isinstance(section_payload.get("simulation"), dict):
                    merged["simulation"] = section_payload["simulation"]
            merged["connectivity"] = section_payload
        else:
            merged[section] = section_payload
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    with open(resolved_path, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2)
        fh.write("\n")
    return JSONResponse({"ok": True, "resolved_path": str(resolved_path), "saved_sections": sections})


@app.post("/api/settings/apply")
async def apply_settings_sections(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="apply payload must be an object")
    sections = _selected_sections(payload)
    settings_payload = payload.get("settings")
    if not isinstance(settings_payload, dict):
        raise HTTPException(status_code=400, detail="settings object is required")
    applied = _apply_settings_sections(runtime.config, settings_payload, sections)
    save_config(runtime.config)
    if "connectivity" in applied:
        await runtime.reconfigure_mqtt(runtime.config.mqtt)
    if "video" in applied:
        video = runtime.config.video
        await runtime.state_store.set_video_modes(
            bool(video.get("enabled", True)),
            str(video.get("ingest_mode", "mqtt_frames")),
            str(video.get("delivery_mode", "websocket_mjpeg")),
        )
    return JSONResponse({"ok": True, "applied_sections": applied})


@app.get("/api/ai-settings")
async def get_ai_settings(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    return {"ai_settings": _normalize_ai_settings(runtime.config.raw.get("ai_settings", {}))}


@app.post("/api/ai-settings")
async def save_ai_settings(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="AI settings payload must be an object")
    settings_payload = payload.get("ai_settings", payload)
    if not isinstance(settings_payload, dict):
        raise HTTPException(status_code=400, detail="ai_settings must be an object")
    runtime.config.raw["ai_settings"] = _normalize_ai_settings(settings_payload)
    save_config(runtime.config)
    return JSONResponse({"ok": True, "ai_settings": runtime.config.raw["ai_settings"]})


def _tts_fetch_sync(service_url: str, service_payload: dict[str, Any]) -> tuple[str, bytes]:
    request = UrlRequest(
        service_url,
        data=json.dumps(service_payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "audio/wav"},
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        return response.headers.get("Content-Type", "audio/wav"), response.read()


@app.post("/api/ai-tts/speech")
async def create_ai_tts_speech(request: Request) -> Response:
    runtime = _runtime(request)
    settings = _normalize_ai_settings(runtime.config.raw.get("ai_settings", {}))
    tts = settings["tts"]
    if not tts["enabled"]:
        raise HTTPException(status_code=400, detail="text to speech is disabled")
    if tts["engine"] != "kokoro_service":
        raise HTTPException(status_code=400, detail="local TTS service is not selected")

    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="speech payload must be an object")
    text = str(payload.get("input", payload.get("text", "")) or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="input text is required")
    if len(text) > 6000:
        raise HTTPException(status_code=413, detail="input exceeds 6000 characters")

    service_payload = {
        "input": text,
        "voice": str(payload.get("voice", tts["voice"]) or tts["voice"]),
        "format": str(payload.get("format", tts["format"]) or tts["format"]),
        "speed": _bounded_float(payload.get("speed", tts["speed"]), default=tts["speed"], minimum=0.5, maximum=2.0),
    }
    service_url = urljoin(str(tts["service_url"]).rstrip("/") + "/", "v1/audio/speech")
    loop = asyncio.get_running_loop()
    try:
        content_type, content = await loop.run_in_executor(
            None, _tts_fetch_sync, service_url, service_payload
        )
        return Response(content=content, media_type=content_type)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") or f"TTS service returned HTTP {exc.code}"
        raise HTTPException(status_code=502, detail=detail) from exc
    except URLError as exc:
        raise HTTPException(status_code=502, detail=f"TTS service is unreachable: {exc.reason}") from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="TTS service request timed out") from exc


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
    updated["rover_availability"] = _rover_availability_policy_from_mqtt(updated)

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
        "broker_port": _parse_int_field(mqtt_payload.get("broker_port", 1883), "broker_port"),
        "topic_prefix": str(mqtt_payload.get("topic_prefix", "")).strip(),
        "client_id": str(mqtt_payload.get("client_id", "")).strip(),
        "control_topic": str(mqtt_payload.get("control_topic", "control/manual")).strip(),
        "state_topic": str(mqtt_payload.get("state_topic", "telemetry/state")).strip(),
        "camera_topic": str(mqtt_payload.get("camera_topic", "camera-feed")).strip(),
        "control_hz": _parse_int_field(mqtt_payload.get("control_hz", 20), "control_hz"),
    })
    mqtt_out["rover_availability"] = _rover_availability_policy_from_mqtt(mqtt_payload)
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
async def replay_sessions(
    request: Request,
    limit: int = 100,
    started_at_from: float | None = None,
    started_at_to: float | None = None,
    order: str = "desc",
) -> dict[str, Any]:
    runtime = _runtime(request)
    return {
        "sessions": runtime.replay_analytics.list_sessions(
            limit=limit,
            started_at_from=started_at_from,
            started_at_to=started_at_to,
            order=order,
        ),
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


@app.get("/api/replay/sessions/{session_id}/summary")
async def replay_session_summary(session_id: str, request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    summary = runtime.replay_analytics.get_session_summary(session_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"session": summary}


@app.get("/api/replay/sessions/{session_id}/metrics")
async def replay_session_metrics(session_id: str, request: Request, refresh: bool = False) -> dict[str, Any]:
    runtime = _runtime(request)
    metrics = runtime.replay_analytics.get_session_metrics(session_id, refresh=refresh)
    if metrics is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"metrics": metrics}


@app.get("/api/replay/sessions/{session_id}/path")
async def replay_session_path(
    session_id: str,
    request: Request,
    downsample: int = 1,
    limit: int | None = None,
) -> dict[str, Any]:
    runtime = _runtime(request)
    path = runtime.replay_analytics.get_session_path(session_id, downsample=downsample, limit=limit)
    if path is None:
        raise HTTPException(status_code=404, detail="session not found")
    return path


@app.get("/api/replay/sessions/{session_id}/events/search")
async def replay_session_events_search(
    session_id: str,
    request: Request,
    event_type: str = "",
    text: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    runtime = _runtime(request)
    result = runtime.replay_analytics.search_session_events(
        session_id,
        event_type=event_type,
        text=text,
        limit=limit,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="session not found")
    return result


@app.post("/api/replay/sessions/compare")
async def replay_sessions_compare(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")
    session_ids = payload.get("session_ids", [])
    if not isinstance(session_ids, list):
        raise HTTPException(status_code=400, detail="session_ids must be a list")
    clean_ids = [str(item).strip() for item in session_ids if str(item).strip()]
    return runtime.replay_analytics.compare_sessions(clean_ids)


@app.post("/api/replay/sessions/resolve")
async def replay_sessions_resolve(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")
    selector = payload.get("selector", payload.get("query", ""))
    timezone_name = _request_timezone_name(request, payload)
    return runtime.replay_analytics.resolve_sessions(
        selector,
        timezone_name=timezone_name,
        active_session_id=runtime.replay_store.current_session_id,
    )


@app.post("/api/replay/sessions/aggregate")
async def replay_sessions_aggregate(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")
    selector = payload.get("selector", payload.get("query"))
    session_ids = payload.get("session_ids", [])
    if session_ids is not None and not isinstance(session_ids, list):
        raise HTTPException(status_code=400, detail="session_ids must be a list")
    timezone_name = _request_timezone_name(request, payload)
    return runtime.replay_analytics.aggregate_sessions(
        session_ids=[str(item).strip() for item in session_ids if str(item).strip()] if isinstance(session_ids, list) else None,
        selector=selector,
        timezone_name=timezone_name,
        active_session_id=runtime.replay_store.current_session_id,
    )


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
    uvicorn.run(
        app,
        host=str(config.gcs["host"]),
        port=int(config.gcs["port"]),
        reload=False,
    )
