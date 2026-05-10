from __future__ import annotations

import asyncio
import copy
import json
import re
import time
from dataclasses import dataclass
from typing import Any

try:
    from gcs_server.scene_map import get_scene_map_payload
    from gcs_server.ai.spatial_query_service import SpatialQueryService
except ModuleNotFoundError:
    from scene_map import get_scene_map_payload
    from ai.spatial_query_service import SpatialQueryService


@dataclass(frozen=True, slots=True)
class AIContextSnapshot:
    prompt: str
    meta: dict[str, Any]


class AIContextService:
    def __init__(self, runtime: Any):
        self._runtime = runtime
        self._spatial = SpatialQueryService()

    async def build_compact_context(
        self,
        user_message: str = "",
        session_id: str = "",
        timezone_name: str = "",
        run_mode: str = "chat",
    ) -> AIContextSnapshot:
        providers = [
            "get_current_rover_state",
            "get_runtime_context",
            "get_settings_context",
            "get_llm_context",
            "get_current_mission_state",
            "get_scene_map_summary",
        ]
        # B4: fetch independent async sources in parallel
        rover, runtime = await asyncio.gather(
            self.get_current_rover_state(),
            self.get_runtime_context(),
        )
        settings = self.get_settings_context()
        llm = self.get_llm_context(session_id=session_id)
        mission = self.get_current_mission_state()
        # B3: load scene payload once and reuse for all spatial queries
        scene_payload = self.load_scene_payload()
        scene = self._get_scene_map_summary_from_payload(scene_payload)
        details: dict[str, Any] = {}

        lower = user_message.lower()
        agent_mode = str(run_mode or "").strip().lower() == "agent"
        if not agent_mode:
            if "in front" in lower or "ahead" in lower:
                max_distance, fov = _parse_front_query(lower)
                details["objects_in_front"] = self._find_objects_in_front_from_payload(
                    scene_payload,
                    max_distance_m=max_distance,
                    fov_deg=fov,
                    rover_state=rover,
                )
                providers.append("find_objects_in_front")
            if "near" in lower and ("object" in lower or "rover" in lower):
                radius = _parse_radius_query(lower, default=50.0)
                details["objects_near_rover"] = self._find_objects_near_rover_from_payload(
                    scene_payload, radius_m=radius, rover_state=rover
                )
                providers.append("find_objects_near_rover")
            known_kinds = frozenset((scene.get("object_kinds") or {}).keys()) if scene.get("available") else None
            kind = _parse_kind_query(lower, known_kinds)
            if kind:
                details["objects_by_kind"] = self._find_objects_by_kind_from_payload(scene_payload, kind)
                providers.append("find_objects_by_kind")
        if "recent" in lower or "happened" in lower:
            details["current_replay"] = self.get_current_replay_summary()
            details["recent_telemetry"] = self.get_recent_telemetry(seconds=120, limit=10)
            providers.extend(["get_current_replay_summary", "get_recent_telemetry"])
        replay_context = self.get_replay_session_context(user_message, timezone_name=timezone_name)
        if replay_context.get("available"):
            details["replay_sessions"] = replay_context
            providers.append("get_replay_session_context")

        context = {
            "generated_at": time.time(),
            "rover": rover,
            "runtime": runtime,
            "settings": settings,
            "llm": llm,
            "mission": mission,
            "scene": scene,
            "details": details,
        }
        max_chars = max(
            _CONTEXT_BUDGET_CHARS_MIN,
            min(
                _CONTEXT_BUDGET_CHARS_MAX,
                int((self._runtime.config.ai_settings or {}).get("ai_context_budget_chars", _CONTEXT_BUDGET_CHARS_DEFAULT)),
            ),
        )
        trimmed_context, dropped = _apply_context_budget(context, set(details.keys()), lower, max_chars)
        # D9: preserve insertion order instead of sorting (sorted() loses always-on vs triggered distinction)
        seen: dict[str, None] = {}
        for p in providers:
            seen[p] = None
        return AIContextSnapshot(
            prompt=_format_context_block(trimmed_context, dropped),
            meta={
                "context_schema_version": 1,
                "context_snapshot": context,
                "context_providers": list(seen),
                "operator_timezone": str(timezone_name or "").strip(),
                "run_mode": "agent" if agent_mode else "chat",
                "budget_chars": max_chars,
                "estimated_chars": _estimate_chars(trimmed_context),
                "dropped_sections": dropped,
            },
        )

    async def get_current_rover_state(self) -> dict[str, Any]:
        snapshot = await self._runtime.state_store.snapshot()
        telemetry = snapshot.get("telemetry") or {}
        broker = snapshot.get("broker") or {}
        return {
            "telemetry_fresh": not bool(broker.get("telemetry_stale", True)),
            "last_telemetry_ts": broker.get("last_telemetry_ts") or 0.0,
            "telemetry_age_s": _age_seconds(broker.get("last_telemetry_ts")),
            "backend": telemetry.get("backend") or self._runtime.config.simulation.get("backend", ""),
            "position": telemetry.get("position") or {},
            "gps": telemetry.get("gps") or {},
            "heading_deg": (telemetry.get("orientation") or {}).get("heading_deg"),
            "speed": telemetry.get("speed") or {},
            "battery": telemetry.get("power") or {},
            "camera": telemetry.get("camera") or {},
            "camera_fresh": not bool(broker.get("camera_stale", True)),
            "last_camera_ts": broker.get("last_camera_ts") or 0.0,
            "camera_age_s": _age_seconds(broker.get("last_camera_ts")),
        }

    async def get_runtime_context(self) -> dict[str, Any]:
        snapshot = await self._runtime.state_store.snapshot()
        return {
            "broker": snapshot.get("broker") or {},
            "controller": snapshot.get("controller") or {},
            "video": _without_latest_frame(snapshot.get("video") or {}),
            "simulation": dict(self._runtime.config.simulation),
            "map": dict(self._runtime.config.map),
            "replay_session_id": self._runtime.replay_store.current_session_id,
        }

    def get_settings_context(self) -> dict[str, Any]:
        config = self._runtime.config
        return {
            "settings_path": str(config.settings_path),
            "mqtt": _pick(
                config.mqtt,
                [
                    "broker_host",
                    "broker_port",
                    "topic_prefix",
                    "client_id",
                    "control_topic",
                    "state_topic",
                    "camera_topic",
                    "control_hz",
                    "telemetry_hz",
                    "telemetry_policy",
                    "gcs_presence_topic",
                    "gcs_presence_timeout_ms",
                    "failsafe_timeout_ms",
                    "control_mode",
                    "digital_throttle_step",
                    "digital_steer_step",
                    "video_endpoint",
                ],
            ),
            "key_bindings": _safe_mapping(config.key_bindings),
            "video": _pick(config.video, ["enabled", "ingest_mode", "delivery_mode"]),
            "gcs": _pick(config.gcs, ["host", "port", "state_backend", "controller_lock_backend", "telemetry_stale_ms"]),
            "simulation": _pick(config.simulation, ["backend", "backend_version", "available_backends"]),
            "map": _pick(config.map, ["site_name", "default_center_lat", "default_center_lon", "default_zoom"]),
            "ai_settings": {
                "tts": _pick(
                    (config.ai_settings.get("tts") or {}) if isinstance(config.ai_settings, dict) else {},
                    ["enabled", "engine", "auto_read", "service_url", "voice", "format", "speed", "browser_fallback", "voice_name", "rate", "pitch"],
                )
            },
        }

    def get_llm_context(self, session_id: str = "") -> dict[str, Any]:
        config = self._runtime.config
        providers = [provider for provider in config.llm_providers if isinstance(provider, dict)]
        routing = config.model_routing if isinstance(config.model_routing, dict) else {}
        session = self._ai_session(session_id)
        session_provider_id = str((session or {}).get("provider_id") or "").strip()
        resolved_provider, resolved_source, resolution_note = _resolve_chat_provider(
            providers,
            routing,
            session_provider_id=session_provider_id,
        )
        return {
            "session": {
                "id": session_id,
                "provider_id": session_provider_id,
                "has_provider_override": bool(session_provider_id),
            },
            "model_routing": _safe_mapping(routing),
            "general_chat_route": _safe_mapping(routing.get("general_chat") or {}),
            "active_chat_provider": self._safe_llm_provider(resolved_provider) if resolved_provider else None,
            "active_chat_provider_source": resolved_source,
            "active_chat_provider_note": resolution_note,
            "providers": [self._safe_llm_provider(provider) for provider in providers],
        }

    def _ai_session(self, session_id: str) -> dict[str, Any] | None:
        clean = str(session_id or "").strip()
        if not clean or not hasattr(self._runtime, "ai_store"):
            return None
        try:
            return self._runtime.ai_store.get_session(clean, include_messages=False)
        except Exception:
            return None

    def _safe_llm_provider(self, provider: dict[str, Any]) -> dict[str, Any]:
        auth_mode = str(provider.get("auth_mode", "env_var"))
        secret_ref = str(provider.get("secret_ref", "")).strip()
        has_stored_secret = False
        if auth_mode == "stored_secret" and secret_ref and hasattr(self._runtime, "secret_store"):
            try:
                has_stored_secret = bool(self._runtime.secret_store.has_secret(secret_ref))
            except Exception:
                has_stored_secret = False
        return {
            "id": provider.get("id", ""),
            "display_name": provider.get("display_name", ""),
            "provider_type": provider.get("provider_type", ""),
            "model_id": provider.get("model_id", ""),
            "base_url": provider.get("base_url", ""),
            "enabled": provider.get("enabled", True),
            "capabilities": list(provider.get("capabilities") or []),
            "auth_mode": auth_mode,
            "auth": {
                "uses_secret": auth_mode in {"env_var", "stored_secret"},
                "secret_ref_configured": bool(secret_ref),
                "has_stored_secret": has_stored_secret,
            },
            "last_check": _pick(provider.get("last_check") or {}, ["status", "ok", "checked_at"]),
        }

    def load_scene_payload(self) -> dict[str, Any] | None:
        backend = str(self._runtime.config.simulation.get("backend") or "3d-env")
        try:
            return get_scene_map_payload(backend=backend, grid_size=32)
        except ValueError:
            return None

    def _get_scene_map_summary_from_payload(self, scene: dict[str, Any] | None) -> dict[str, Any]:
        backend = str(self._runtime.config.simulation.get("backend") or "3d-env")
        summary = self._spatial.get_scene_summary(scene)
        summary["backend"] = summary.get("backend") or backend
        summary["site_name"] = str(self._runtime.config.map.get("site_name", "default-site"))
        return summary

    def get_scene_map_summary(self) -> dict[str, Any]:
        return self._get_scene_map_summary_from_payload(self.load_scene_payload())

    def _find_objects_in_front_from_payload(
        self,
        scene: dict[str, Any] | None,
        max_distance_m: float = 100.0,
        fov_deg: float = 20.0,
        rover_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._spatial.find_objects_in_front(
            scene,
            rover_state or {},
            max_distance_m=max_distance_m,
            fov_deg=fov_deg,
        )

    def find_objects_in_front(
        self,
        max_distance_m: float = 100.0,
        fov_deg: float = 20.0,
        rover_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._find_objects_in_front_from_payload(
            self.load_scene_payload(),
            max_distance_m=max_distance_m,
            fov_deg=fov_deg,
            rover_state=rover_state,
        )

    def _find_objects_near_rover_from_payload(
        self,
        scene: dict[str, Any] | None,
        radius_m: float = 50.0,
        rover_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._spatial.find_objects_near(scene, rover_state or {}, radius_m=radius_m)

    def find_objects_near_rover(
        self,
        radius_m: float = 50.0,
        rover_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._find_objects_near_rover_from_payload(
            self.load_scene_payload(), radius_m=radius_m, rover_state=rover_state
        )

    def _find_objects_by_kind_from_payload(self, scene: dict[str, Any] | None, kind: str) -> dict[str, Any]:
        return self._spatial.find_objects_by_kind(scene, kind)

    def find_objects_by_kind(self, kind: str) -> dict[str, Any]:
        return self._find_objects_by_kind_from_payload(self.load_scene_payload(), kind)

    def find_objects_to_left(
        self,
        max_distance_m: float = 100.0,
        angle_width_deg: float = 90.0,
        kinds: list[str] | None = None,
        rover_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._spatial.find_objects_to_left(
            self.load_scene_payload(),
            rover_state or {},
            max_distance_m=max_distance_m,
            angle_width_deg=angle_width_deg,
            kinds=kinds,
        )

    def find_objects_to_right(
        self,
        max_distance_m: float = 100.0,
        angle_width_deg: float = 90.0,
        kinds: list[str] | None = None,
        rover_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._spatial.find_objects_to_right(
            self.load_scene_payload(),
            rover_state or {},
            max_distance_m=max_distance_m,
            angle_width_deg=angle_width_deg,
            kinds=kinds,
        )

    def find_nearest_objects(
        self,
        limit: int = 5,
        max_distance_m: float | None = None,
        kinds: list[str] | None = None,
        rover_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._spatial.find_nearest_objects(
            self.load_scene_payload(),
            rover_state or {},
            limit=limit,
            max_distance_m=max_distance_m,
            kinds=kinds,
        )

    def resolve_target_description(self, target: dict[str, Any], rover_state: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._spatial.resolve_target_description(self.load_scene_payload(), rover_state or {}, target)

    def get_current_replay_summary(self) -> dict[str, Any]:
        current_id = self._runtime.replay_store.current_session_id
        if not current_id:
            return {"active": False, "session_id": None}
        summary = self._runtime.replay_store.get_session_summary(current_id)
        return {"active": True, **(summary or {"session_id": current_id})}

    def get_recent_telemetry(self, seconds: int = 120, limit: int = 20) -> list[dict[str, Any]]:
        return self._runtime.replay_store.get_recent_telemetry(seconds=seconds, limit=limit)

    def get_replay_session_context(self, user_message: str, *, timezone_name: str = "") -> dict[str, Any]:
        analytics = getattr(self._runtime, "replay_analytics", None)
        if analytics is None:
            return {"available": False}
        return analytics.build_ai_replay_context(
            user_message,
            active_session_id=self._runtime.replay_store.current_session_id,
            timezone_name=timezone_name,
        )

    def get_current_mission_state(self) -> dict[str, Any]:
        return {
            "active": False,
            "status": "no_active_mission",
            "summary": "No mission storage or active mission is implemented yet.",
        }

def _format_context_block(context: dict[str, Any], dropped: list[str] | None = None) -> str:
    header = (
        "Live GCS current context. Treat these structured facts as more current than conversation history. "
        "This chat is read-only and must not publish control commands."
    )
    if dropped:
        header += f" Context budget applied; omitted: {', '.join(dropped)}."
    return f"{header}\n{json.dumps(context, separators=(',', ':'), sort_keys=True)}"


def _without_latest_frame(video: dict[str, Any]) -> dict[str, Any]:
    out = dict(video)
    latest = out.pop("latest_frame", None) or {}
    if latest:
        out["latest_frame_meta"] = {
            key: value
            for key, value in latest.items()
            if key not in {"data", "payload", "jpeg"}
        }
    return out


def _pick(source: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    return {key: source.get(key) for key in keys if key in source}


def _safe_mapping(source: Any) -> dict[str, Any]:
    return dict(source) if isinstance(source, dict) else {}


def _resolve_chat_provider(
    providers: list[dict[str, Any]],
    routing: dict[str, Any],
    *,
    session_provider_id: str = "",
) -> tuple[dict[str, Any] | None, str, str]:
    if session_provider_id:
        provider = _find_provider(providers, session_provider_id)
        if provider is None:
            return None, "session_override", "session provider override was not found"
        if not provider.get("enabled", True):
            return provider, "session_override", "session provider override is disabled"
        return provider, "session_override", ""

    rule = routing.get("general_chat", {}) if isinstance(routing, dict) else {}
    if isinstance(rule, dict):
        candidate_ids = [
            str(rule.get("primary_provider_id", "")).strip(),
            *[str(item).strip() for item in rule.get("fallback_provider_ids", []) if str(item).strip()],
        ]
        for provider_id in candidate_ids:
            provider = _find_provider(providers, provider_id)
            if provider and provider.get("enabled", True):
                return provider, "general_chat_route", ""

    provider = next((item for item in providers if item.get("enabled", True)), None)
    return provider, "first_enabled_provider" if provider else "none", "" if provider else "no enabled provider is configured"


def _find_provider(providers: list[dict[str, Any]], provider_id: str) -> dict[str, Any] | None:
    clean = str(provider_id or "").strip()
    if not clean:
        return None
    return next((provider for provider in providers if str(provider.get("id")) == clean), None)


def _age_seconds(ts: Any) -> float | None:
    try:
        value = float(ts or 0.0)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return max(0.0, time.time() - value)


def _parse_front_query(text: str) -> tuple[float, float]:
    distance = _parse_radius_query(text, default=100.0)
    fov_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:degree|deg)", text)
    fov = float(fov_match.group(1)) if fov_match else 20.0
    return distance, fov


def _parse_radius_query(text: str, default: float) -> float:
    match = re.search(r"within\s+(\d+(?:\.\d+)?)\s*(?:m|meter|meters)", text)
    if not match:
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|meter|meters)", text)
    return float(match.group(1)) if match else default


def _parse_kind_query(text: str, known_kinds: frozenset[str] | None = None) -> str:
    match = re.search(r"(?:kind|type)\s+([a-z0-9_-]+)", text)
    if match:
        return match.group(1)
    if known_kinds:
        for word in re.findall(r"[a-z0-9_-]+", text):
            if word in known_kinds:
                return word
    return ""


# ---------------------------------------------------------------------------
# Context budget helpers
# ---------------------------------------------------------------------------

_CONTEXT_BUDGET_CHARS_DEFAULT = 24000
_CONTEXT_BUDGET_CHARS_MIN = 4000
_CONTEXT_BUDGET_CHARS_MAX = 200000

# Keywords that signal a user message references a specific always-on section.
# If a section's keywords appear in the message it is protected from phase-1 drops.
_SETTINGS_KEYWORDS: frozenset[str] = frozenset({
    "mqtt", "broker", "topic", "config", "settings", "binding", "video",
    "port", "control_hz", "telemetry_hz", "failsafe", "presence", "client_id",
    "ingest", "delivery", "key_bind",
})
_LLM_KEYWORDS: frozenset[str] = frozenset({
    "provider", "model", "api", "routing", "llm", "openai", "ollama",
    "anthropic", "groq", "mistral", "cohere", "openrouter", "gemini",
    "nvidia", "huggingface", "together", "lm_studio",
})
_SCENE_KEYWORDS: frozenset[str] = frozenset({
    "terrain", "map", "object", "road", "spawn", "scene", "bounds",
    "obstacle", "landmark", "tree", "rock", "building", "structure",
    "site", "grid",
})


def _estimate_chars(data: Any) -> int:
    return len(json.dumps(data, separators=(",", ":")))


def _message_references(lower: str, keywords: frozenset[str]) -> bool:
    return any(kw in lower for kw in keywords)


def _trim_objects_list(detail: dict[str, Any], max_objects: int) -> dict[str, Any]:
    out = dict(detail)
    objects = out.get("objects")
    if isinstance(objects, list) and len(objects) > max_objects:
        out["objects"] = objects[:max_objects]
        out["trimmed"] = True
        out["original_count"] = len(objects)
    return out


def _trim_replay_sessions(replay: dict[str, Any], max_sessions: int) -> dict[str, Any]:
    out = dict(replay)
    sessions = out.get("sessions")
    if isinstance(sessions, list) and len(sessions) > max_sessions:
        out["sessions"] = sessions[:max_sessions]
        out["trimmed"] = True
        out["original_count"] = len(sessions)
    return out


def _apply_context_budget(
    context: dict[str, Any],
    triggered_detail_keys: set[str],
    lower: str,
    max_chars: int,
) -> tuple[dict[str, Any], list[str]]:
    """Return (trimmed_context, dropped_section_names).

    Three-phase strategy:
      Phase 1 — drop non-relevant always-on background sections first.
      Phase 2 — trim large triggered detail sections (preserve, reduce size).
      Phase 3 — last resort: drop triggered detail sections.
    rover, runtime, and mission are never touched.
    """
    if _estimate_chars(context) <= max_chars:
        return context, []

    ctx = copy.deepcopy(context)
    dropped: list[str] = []

    # Phase 1: drop background sections the message doesn't reference.
    # Settings/LLM are less useful than scene facts for rover-operation prompts,
    # so shed them first when the prompt does not explicitly ask for them.
    for key, keywords in (
        ("settings", _SETTINGS_KEYWORDS),
        ("llm", _LLM_KEYWORDS),
        ("scene", _SCENE_KEYWORDS),
    ):
        if _estimate_chars(ctx) <= max_chars:
            return ctx, dropped
        if key in ctx and not _message_references(lower, keywords):
            del ctx[key]
            dropped.append(key)

    if _estimate_chars(ctx) <= max_chars:
        return ctx, dropped

    # Phase 2: trim triggered detail sections — reduce size, do not drop
    details = ctx.get("details")
    if isinstance(details, dict):
        # replay_sessions first — typically the largest
        if "replay_sessions" in details:
            details["replay_sessions"] = _trim_replay_sessions(details["replay_sessions"], max_sessions=5)
            if _estimate_chars(ctx) <= max_chars:
                return ctx, dropped

        # recent_telemetry: first pass 10 → 5
        if "recent_telemetry" in details:
            entries = details["recent_telemetry"]
            if isinstance(entries, list) and len(entries) > 5:
                details["recent_telemetry"] = entries[:5]
                if _estimate_chars(ctx) <= max_chars:
                    return ctx, dropped

        # object query results → top 10 by distance (already sorted)
        for obj_key in ("objects_in_front", "objects_near_rover", "objects_by_kind"):
            if obj_key in details:
                details[obj_key] = _trim_objects_list(details[obj_key], max_objects=10)
        if _estimate_chars(ctx) <= max_chars:
            return ctx, dropped

        # recent_telemetry: second pass 5 → 3
        if "recent_telemetry" in details:
            entries = details["recent_telemetry"]
            if isinstance(entries, list) and len(entries) > 3:
                details["recent_telemetry"] = entries[:3]
                if _estimate_chars(ctx) <= max_chars:
                    return ctx, dropped

    # Phase 3: last resort — drop triggered sections entirely
    details = ctx.get("details")
    if isinstance(details, dict):
        for key in (
            "replay_sessions",
            "recent_telemetry",
            "current_replay",
            "objects_by_kind",
            "objects_near_rover",
            "objects_in_front",
        ):
            if _estimate_chars(ctx) <= max_chars:
                break
            if key in details:
                del details[key]
                dropped.append(f"details.{key}")
        if not details:
            ctx.pop("details", None)

    return ctx, dropped
