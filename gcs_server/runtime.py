from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from gcs_server.ai.controller_mission_adapter_factory import build_controller_mission_adapter
from gcs_server.ai.coordinate_frame import Origin
from gcs_server.ai.mission_draft_service import MissionDraftService
from gcs_server.ai.mission_execution_service import MissionExecutionService
from gcs_server.ai.mission_execution_session import MissionExecutionSessions
from gcs_server.ai.mission_store import MissionStore
from gcs_server.ai.secret_store import SecretStore
from gcs_server.ai.session_store import AISessionStore
from gcs_server.config import AppConfig, ROOT_DIR
from gcs_server.control import ControlService
from gcs_server.mqtt_service import MQTTRuntime
from gcs_server.replay_analytics import ReplayAnalyticsService
from gcs_server.replay_store import ReplayStore
from gcs_server.state import LocalStateBackend
from gcs_server.telemetry import normalize_telemetry
from gcs_server.ws import WebSocketManager


GCS_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = ROOT_DIR / ".runtime"
LEGACY_SECRET_DB_PATH = RUNTIME_DIR / "secrets" / "llm_secrets.sqlite3"


def _resolve_replay_db_path(path: object) -> Path:
    db_path = Path(str(path))
    if db_path.is_absolute():
        return db_path
    return GCS_DIR / db_path


def _ai_worker_count(value: object) -> int:
    try:
        return max(1, min(16, int(value)))
    except (TypeError, ValueError):
        return 4


@dataclass(slots=True)
class AppRuntime:
    config: AppConfig
    state_store: LocalStateBackend
    ws_manager: WebSocketManager
    mqtt_runtime: MQTTRuntime
    control_service: ControlService
    replay_store: ReplayStore
    replay_analytics: ReplayAnalyticsService
    ai_store: AISessionStore
    mission_draft_service: MissionDraftService
    mission_execution_service: MissionExecutionService
    mission_store: MissionStore
    secret_store: SecretStore
    ai_executor: ThreadPoolExecutor
    mission_execution_sessions: MissionExecutionSessions

    async def reconfigure_mqtt(self, mqtt_config: dict[str, object]) -> None:
        self.config.raw["mqtt"] = dict(mqtt_config)
        self.mqtt_runtime.update_config(self.config.mqtt)
        await self.control_service.update_control_hz(int(self.config.mqtt["control_hz"]))
        await self.mqtt_runtime.stop()
        await self.mqtt_runtime.start()


async def build_runtime(config: AppConfig) -> AppRuntime:
    replay_store = ReplayStore(
        db_path=_resolve_replay_db_path(config.logging["replay_db_path"]),
        backend_type=str(config.simulation["backend"]),
        backend_version=str(config.simulation.get("backend_version", "dev")),
        source_node_id=str(config.mqtt.get("client_id") or "gcs-web"),
        site_name=str(config.map.get("site_name", "default-site")),
    )
    if config.logging.get("auto_start_session", True):
        replay_store.ensure_session()
    ai_sessions_db_path = _resolve_replay_db_path(
        config.logging.get("ai_sessions_db_path", "data/gcs_ai_sessions.sqlite3")
    )
    ai_store = AISessionStore(db_path=ai_sessions_db_path)
    mission_draft_service = MissionDraftService(db_path=ai_sessions_db_path)
    mission_store = MissionStore(db_path=ai_sessions_db_path)
    controller_mission_adapter = build_controller_mission_adapter(
        config.logging,
        path_resolver=_resolve_replay_db_path,
    )
    def _resolve_mission_origin(operation_id: str) -> Origin | None:
        """ADR 0022 per-Mission datum: map an internal operation to its flat
        Mission's coordinate Origin (None falls back to the scene georeference)."""
        mission = mission_store.get_by_operation_id(operation_id)
        if mission is None:
            return None
        return mission_store.get_origin_datum(str(mission.get("id") or ""))

    mission_execution_service = MissionExecutionService(
        db_path=ai_sessions_db_path,
        controller_adapter=controller_mission_adapter,
        origin_resolver=_resolve_mission_origin,
    )
    replay_analytics = ReplayAnalyticsService(replay_store)
    secret_store = SecretStore(
        db_path=_resolve_replay_db_path(config.logging.get("llm_secrets_db_path", "data/gcs_llm_secrets.sqlite3")),
    )
    if secret_store.count() == 0 and LEGACY_SECRET_DB_PATH.exists():
        secret_store.migrate_from(LEGACY_SECRET_DB_PATH)
    ai_executor = ThreadPoolExecutor(
        max_workers=_ai_worker_count(config.gcs.get("ai_worker_threads", 4)),
        thread_name_prefix="gcs-ai-llm",
    )
    state_store = LocalStateBackend(
        telemetry_stale_ms=int(config.gcs["telemetry_stale_ms"]),
    )
    await state_store.set_video_modes(
        enabled=bool(config.video["enabled"]),
        ingest_mode=str(config.video["ingest_mode"]),
        delivery_mode=str(config.video["delivery_mode"]),
    )
    ws_manager = WebSocketManager()
    mqtt_runtime = MQTTRuntime(
        config.mqtt,
        state_store,
        ws_manager,
        replay_store=replay_store,
        backend_resolver=lambda: str(config.simulation["backend"]),
        telemetry_normalizer=normalize_telemetry,
    )
    control_service = ControlService(
        publish_func=mqtt_runtime.publish_control,
        controller_store=state_store,
        control_hz=int(config.mqtt["control_hz"]),
        replay_store=replay_store,
    )
    return AppRuntime(
        config=config,
        state_store=state_store,
        ws_manager=ws_manager,
        mqtt_runtime=mqtt_runtime,
        control_service=control_service,
        replay_store=replay_store,
        replay_analytics=replay_analytics,
        ai_store=ai_store,
        mission_draft_service=mission_draft_service,
        mission_execution_service=mission_execution_service,
        mission_store=mission_store,
        secret_store=secret_store,
        ai_executor=ai_executor,
        mission_execution_sessions=MissionExecutionSessions(),
    )
