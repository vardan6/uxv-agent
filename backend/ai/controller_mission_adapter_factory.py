from __future__ import annotations

from pathlib import Path

from backend.ai.controller_mission_adapter import (
    ControllerMissionAdapter,
    ControllerMissionAdapterError,
    FileSinkControllerMissionAdapter,
    JsonFileControllerMissionAdapter,
    MavlinkControllerMissionAdapter,
    MavsdkControllerMissionAdapter,
)


def build_controller_mission_adapter(
    logging_config: dict[str, object],
    *,
    path_resolver,
) -> ControllerMissionAdapter:
    state_path = path_resolver(logging_config.get("controller_mission_state_path", "data/controller_mission_adapter.json"))
    adapter_name = str(logging_config.get("controller_mission_adapter", "json_file") or "json_file").strip().lower()
    if adapter_name == "json_file":
        return JsonFileControllerMissionAdapter(state_path=state_path)
    if adapter_name == "file_sink":
        sink_dir = path_resolver(logging_config.get("controller_mission_sink_dir", "data/fc_sink"))
        return FileSinkControllerMissionAdapter(sink_dir=sink_dir)
    if adapter_name == "mavlink":
        connection_url = str(logging_config.get("controller_mission_mavlink_url") or "").strip()
        if not connection_url:
            raise ControllerMissionAdapterError(
                "controller_mission_mavlink_url is required when controller_mission_adapter is 'mavlink'"
            )
        return MavlinkControllerMissionAdapter(
            connection_url=connection_url,
            state_path=state_path,
            heartbeat_timeout_s=float(logging_config.get("controller_mission_heartbeat_timeout_s", 5.0) or 5.0),
            request_timeout_s=float(logging_config.get("controller_mission_request_timeout_s", 5.0) or 5.0),
            source_system=int(logging_config.get("controller_mission_source_system", 245) or 245),
            source_component=int(logging_config.get("controller_mission_source_component", 190) or 190),
        )
    if adapter_name == "mavsdk":
        connection_url = str(
            logging_config.get("controller_mission_mavsdk_url")
            or logging_config.get("controller_mission_mavlink_url")
            or ""
        ).strip()
        if not connection_url:
            raise ControllerMissionAdapterError(
                "controller_mission_mavsdk_url (or controller_mission_mavlink_url) is required "
                "when controller_mission_adapter is 'mavsdk'"
            )
        return MavsdkControllerMissionAdapter(
            connection_url=connection_url,
            state_path=state_path,
            heartbeat_timeout_s=float(logging_config.get("controller_mission_heartbeat_timeout_s", 5.0) or 5.0),
            request_timeout_s=float(logging_config.get("controller_mission_request_timeout_s", 5.0) or 5.0),
        )
    raise ControllerMissionAdapterError(f"unsupported controller mission adapter: {adapter_name}")
