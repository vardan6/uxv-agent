from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from backend.ai.controller_mission_adapter_factory import build_controller_mission_adapter
from backend.ai.coordinate_frame import Origin
from backend.ai.mission_execution_service import MissionExecutionService
from backend.ai.mission_execution_session import MissionExecutionSessions
from backend.ai.mission_store import MissionStore
from backend.ai.operational_constraints_store import OperationalConstraintsStore
from backend.ai.secret_store import SecretStore
from backend.ai.session_store import AISessionStore
from backend.ai.vehicle_profile import VehicleProfile, resolve_active_profile
from backend.config import AppConfig, ROOT_DIR
from backend.control import ControlService
from backend.mqtt_service import MQTTRuntime
from backend.replay_analytics import ReplayAnalyticsService
from backend.replay_store import ReplayStore
from backend.state import LocalStateBackend
from backend.telemetry import normalize_telemetry
from backend.ws import WebSocketManager


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
    mission_execution_service: MissionExecutionService
    mission_store: MissionStore
    operational_constraints_store: OperationalConstraintsStore
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
    mission_store = MissionStore(db_path=ai_sessions_db_path)
    operational_constraints_store = OperationalConstraintsStore(db_path=ai_sessions_db_path)
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

    def _resolve_profile() -> VehicleProfile:
        """The operator's persisted vehicle-profile selection, read per call so a
        change through /api/vehicle-profile/active takes effect without a
        restart."""
        return resolve_active_profile(config)

    mission_execution_service = MissionExecutionService(
        db_path=ai_sessions_db_path,
        controller_adapter=controller_mission_adapter,
        origin_resolver=_resolve_mission_origin,
        profile_resolver=_resolve_profile,
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
        mission_execution_service=mission_execution_service,
        mission_store=mission_store,
        operational_constraints_store=operational_constraints_store,
        secret_store=secret_store,
        ai_executor=ai_executor,
        mission_execution_sessions=MissionExecutionSessions(),
    )
