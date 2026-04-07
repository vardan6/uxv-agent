from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any

import paho.mqtt.client as mqtt

try:
    from gcs_server.video import decode_mqtt_frame
except ModuleNotFoundError:
    from video import decode_mqtt_frame


def _topic_join(prefix: str, leaf: str) -> str:
    p = (prefix or "").strip().rstrip("/")
    l = (leaf or "").strip().strip("/")
    if p and l:
        return f"{p}/{l}"
    return p or l


logger = logging.getLogger(__name__)


class MQTTRuntime:
    def __init__(self, cfg: dict[str, Any], state_store, ws_manager):
        self._cfg = cfg
        self._state_store = state_store
        self._ws_manager = ws_manager
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: mqtt.Client | None = None
        self._started = False
        self._publish_lock = threading.Lock()

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._loop = asyncio.get_running_loop()
        client_id = (self._cfg.get("client_id") or "gcs-web").strip()
        self._client = mqtt.Client(client_id=client_id, clean_session=True)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=2, max_delay=15)
        self._client.connect_async(
            str(self._cfg["broker_host"]),
            int(self._cfg["broker_port"]),
            keepalive=30,
        )
        self._client.loop_start()
        await self._state_store.set_broker_state("connecting", False)

    async def stop(self) -> None:
        self._started = False
        if self._client is None:
            return
        try:
            self._client.loop_stop()
            self._client.disconnect()
        finally:
            self._client = None

    def update_config(self, cfg: dict[str, Any]) -> None:
        self._cfg = cfg

    async def publish_control(self, frame: dict[str, Any]) -> None:
        if self._client is None:
            logger.warning("Skipping control publish because MQTT client is not initialized")
            return
        topic = _topic_join(self._cfg["topic_prefix"], self._cfg["control_topic"])
        payload = json.dumps(frame, separators=(",", ":"))
        with self._publish_lock:
            info = self._client.publish(topic, payload=payload, qos=0, retain=False)
        logger.info(
            "Published control frame topic=%s rc=%s mid=%s connected=%s payload=%s",
            topic,
            info.rc,
            getattr(info, "mid", None),
            self._client.is_connected(),
            payload,
        )

    def _on_connect(self, client, _userdata, _flags, rc):
        if self._loop is None:
            return
        if rc == 0:
            state_topic = _topic_join(self._cfg["topic_prefix"], self._cfg["state_topic"])
            camera_topic = _topic_join(self._cfg["topic_prefix"], self._cfg["camera_topic"])
            client.subscribe(state_topic, qos=0)
            client.subscribe(camera_topic, qos=0)
            self._schedule(self._state_store.set_broker_state("connected", True))
            self._schedule(self._ws_manager.broadcast({"type": "broker", "data": {"status": "connected", "connected": True}}))
        else:
            msg = f"connect failed rc={rc}"
            self._schedule(self._state_store.set_broker_state("connect_failed", False, msg))

    def _on_disconnect(self, _client, _userdata, rc):
        if self._loop is None:
            return
        status = "reconnecting" if rc != 0 else "disconnected"
        self._schedule(self._state_store.set_broker_state(status, False))
        self._schedule(self._ws_manager.broadcast({"type": "broker", "data": {"status": status, "connected": False}}))

    def _on_message(self, _client, _userdata, msg):
        if self._loop is None:
            return
        state_topic = _topic_join(self._cfg["topic_prefix"], self._cfg["state_topic"])
        camera_topic = _topic_join(self._cfg["topic_prefix"], self._cfg["camera_topic"])
        if msg.topic == state_topic:
            try:
                payload = json.loads(msg.payload.decode("utf-8"))
            except Exception:
                return
            self._schedule(self._handle_telemetry(payload))
        elif msg.topic == camera_topic:
            frame = decode_mqtt_frame(msg.payload)
            self._schedule(self._handle_camera(frame))

    async def _handle_telemetry(self, payload: dict[str, Any]) -> None:
        await self._state_store.set_telemetry(payload)
        snapshot = await self._state_store.snapshot()
        await self._ws_manager.broadcast({
            "type": "telemetry",
            "data": payload,
            "broker": snapshot["broker"],
        })

    async def _handle_camera(self, frame: dict[str, Any]) -> None:
        await self._state_store.set_video_frame(frame)
        modes = await self._state_store.get_video_modes()
        if not modes.get("enabled", True):
            return
        if modes.get("delivery_mode") != "websocket_mjpeg":
            return
        await self._ws_manager.broadcast({"type": "video_frame", "data": frame})

    def _schedule(self, coroutine) -> None:
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(coroutine, self._loop)
