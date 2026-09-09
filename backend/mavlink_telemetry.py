from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class MavlinkTelemetryBridge:
    """Background thread that listens for GLOBAL_POSITION_INT from a MAVLink source
    and broadcasts normalized telemetry to GCS browser clients via ws_manager.

    Enabled by setting MAVLINK_TELEMETRY_URL in the environment, e.g.:
        MAVLINK_TELEMETRY_URL=udpout:127.0.0.1:14550
    """

    def __init__(
        self,
        connection_url: str,
        loop: asyncio.AbstractEventLoop,
        broadcast: Callable[[dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> None:
        self._url = connection_url
        self._loop = loop
        self._broadcast = broadcast
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="mavlink-telemetry-bridge"
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:
        try:
            from pymavlink import mavutil
        except ImportError:
            logger.warning("pymavlink not installed; MavlinkTelemetryBridge disabled")
            return
        try:
            conn = mavutil.mavlink_connection(
                self._url, source_system=255, source_component=190
            )
        except Exception as exc:
            logger.warning("MavlinkTelemetryBridge: cannot open %s: %s", self._url, exc)
            return
        logger.info("MavlinkTelemetryBridge: listening on %s", self._url)
        while self._running:
            msg = conn.recv_match(
                type=["GLOBAL_POSITION_INT"],
                blocking=True,
                timeout=1.0,
            )
            if msg is None or msg.get_type() == "BAD_DATA":
                continue
            t = msg.get_type()
            if t != "GLOBAL_POSITION_INT":
                continue
            lat = msg.lat / 1e7
            lon = msg.lon / 1e7
            alt = msg.alt / 1000.0
            hdg = msg.hdg / 100.0 if msg.hdg != 65535 else 0.0
            telemetry: dict[str, Any] = {
                "backend": "mav_sim",
                "timestamp": time.time(),
                "gps": {"lat": lat, "lon": lon, "alt": alt},
                "orientation": {"heading_deg": hdg},
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                "speed": {"m_s": 0.0, "km_h": 0.0},
                "camera": {"mode": "", "video_endpoint": ""},
                "power": {
                    "battery_pct": 0.0,
                    "voltage_v": 0.0,
                    "current_a": 0.0,
                    "temperature_c": 0.0,
                },
                "georeference": {},
                "validity": {
                    "has_gps": True,
                    "has_position": False,
                    "has_heading": hdg != 0.0,
                    "has_speed": False,
                },
                "position_frame": "gps_wgs84",
                "map_pose": {"lat": lat, "lon": lon, "alt": alt, "heading_deg": hdg},
            }
            asyncio.run_coroutine_threadsafe(
                self._broadcast({"type": "telemetry", "data": telemetry}),
                self._loop,
            )
