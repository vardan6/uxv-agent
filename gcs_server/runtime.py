from __future__ import annotations

from dataclasses import dataclass

try:
    from gcs_server.config import AppConfig
    from gcs_server.control import ControlService
    from gcs_server.mqtt_service import MQTTRuntime
    from gcs_server.replay_store import ReplayStore
    from gcs_server.state import LocalStateBackend
    from gcs_server.telemetry import normalize_telemetry
    from gcs_server.ws import WebSocketManager
except ModuleNotFoundError:
    from config import AppConfig
    from control import ControlService
    from mqtt_service import MQTTRuntime
    from replay_store import ReplayStore
    from state import LocalStateBackend
    from telemetry import normalize_telemetry
    from ws import WebSocketManager


@dataclass(slots=True)
class AppRuntime:
    config: AppConfig
    state_store: LocalStateBackend
    ws_manager: WebSocketManager
    mqtt_runtime: MQTTRuntime
    control_service: ControlService
    replay_store: ReplayStore

    async def reconfigure_mqtt(self, mqtt_config: dict[str, object]) -> None:
        self.config.raw["mqtt"] = dict(mqtt_config)
        self.mqtt_runtime.update_config(self.config.mqtt)
        await self.control_service.update_control_hz(int(self.config.mqtt["control_hz"]))
        await self.mqtt_runtime.stop()
        await self.mqtt_runtime.start()


async def build_runtime(config: AppConfig) -> AppRuntime:
    replay_store = ReplayStore(
        db_path=config.logging["replay_db_path"],
        backend_type=str(config.simulation["backend"]),
        backend_version=str(config.simulation.get("backend_version", "dev")),
        source_node_id=str(config.mqtt.get("client_id") or "gcs-web"),
        site_name=str(config.map.get("site_name", "default-site")),
    )
    if config.logging.get("auto_start_session", True):
        replay_store.ensure_session()
    state_store = LocalStateBackend(
        telemetry_stale_ms=int(config.gcs["telemetry_stale_ms"]),
        controller_lease_ms=int(config.gcs["controller_lease_ms"]),
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
    )
