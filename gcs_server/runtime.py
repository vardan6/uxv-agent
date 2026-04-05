from __future__ import annotations

from dataclasses import dataclass

from gcs_server.config import AppConfig
from gcs_server.control import ControlService
from gcs_server.mqtt_service import MQTTRuntime
from gcs_server.state import LocalStateBackend
from gcs_server.ws import WebSocketManager


@dataclass(slots=True)
class AppRuntime:
    config: AppConfig
    state_store: LocalStateBackend
    ws_manager: WebSocketManager
    mqtt_runtime: MQTTRuntime
    control_service: ControlService


async def build_runtime(config: AppConfig) -> AppRuntime:
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
    mqtt_runtime = MQTTRuntime(config.mqtt, state_store, ws_manager)
    control_service = ControlService(
        publish_func=mqtt_runtime.publish_control,
        controller_store=state_store,
        control_hz=int(config.mqtt["control_hz"]),
    )
    return AppRuntime(
        config=config,
        state_store=state_store,
        ws_manager=ws_manager,
        mqtt_runtime=mqtt_runtime,
        control_service=control_service,
    )
