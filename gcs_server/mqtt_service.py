from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
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
PRESENCE_PUBLISH_INTERVAL_S = 30.0


class MQTTRuntime:
    def __init__(self, cfg: dict[str, Any], state_store, ws_manager, replay_store=None, backend_resolver=None, telemetry_normalizer=None):
        self._cfg = cfg
        self._state_store = state_store
        self._ws_manager = ws_manager
        self._replay_store = replay_store
        self._backend_resolver = backend_resolver or (lambda: "3d-env")
        self._telemetry_normalizer = telemetry_normalizer or (lambda payload, backend: payload)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: mqtt.Client | None = None
        self._started = False
        self._publish_lock = threading.Lock()
        self._presence_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._loop = asyncio.get_running_loop()
        client_id = self._gcs_id()
        self._client = mqtt.Client(client_id=client_id, clean_session=True)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=2, max_delay=15)
        self._client.will_set(
            self._presence_topic(),
            payload=json.dumps(self._presence_payload(False), separators=(",", ":")),
            qos=0,
            retain=True,
        )
        self._client.connect_async(
            str(self._cfg["broker_host"]),
            int(self._cfg["broker_port"]),
            keepalive=30,
        )
        self._client.loop_start()
        self._presence_task = asyncio.create_task(self._presence_loop(), name="gcs-presence-loop")
        await self._state_store.set_broker_state("connecting", False)
        if self._replay_store is not None:
            self._replay_store.log_runtime_event(
                "mqtt_start",
                {"broker_host": str(self._cfg["broker_host"]), "broker_port": int(self._cfg["broker_port"])},
            )

    async def stop(self) -> None:
        self._started = False
        if self._presence_task is not None:
            self._presence_task.cancel()
            try:
                await self._presence_task
            except asyncio.CancelledError:
                pass
            self._presence_task = None
        await self.publish_presence_snapshot(force_active=False)
        if self._client is None:
            return
        try:
            self._client.loop_stop()
            self._client.disconnect()
        finally:
            self._client = None
        if self._replay_store is not None:
            self._replay_store.log_runtime_event("mqtt_stop", {})

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
        if self._replay_store is not None:
            self._replay_store.log_runtime_event(
                "mqtt_control_published",
                {"topic": topic, "mid": getattr(info, "mid", None), "rc": info.rc},
            )

    async def publish_presence_snapshot(self, force_active: bool | None = None) -> None:
        if self._client is None:
            return
        browser_count = await self._ws_manager.connection_count()
        controller = await self._state_store.controller_snapshot()
        is_active = browser_count > 0 if force_active is None else bool(force_active)
        payload = self._presence_payload(
            is_active,
            browser_count=browser_count,
            active_controller_id=controller.get("active_client_id"),
        )
        with self._publish_lock:
            self._client.publish(
                self._presence_topic(),
                payload=json.dumps(payload, separators=(",", ":")),
                qos=0,
                retain=True,
            )

    def _on_connect(self, client, _userdata, _flags, rc):
        if self._loop is None:
            return
        if rc == 0:
            state_topic = _topic_join(self._cfg["topic_prefix"], self._cfg["state_topic"])
            camera_topic = _topic_join(self._cfg["topic_prefix"], self._cfg["camera_topic"])
            client.subscribe(state_topic, qos=0)
            client.subscribe(camera_topic, qos=0)
            if self._replay_store is not None:
                self._replay_store.log_runtime_event(
                    "mqtt_connected",
                    {"state_topic": state_topic, "camera_topic": camera_topic},
                )
            self._schedule(self._state_store.set_broker_state("connected", True))
            self._schedule(self._ws_manager.broadcast({"type": "broker", "data": {"status": "connected", "connected": True}}))
            self._schedule(self.publish_presence_snapshot())
        else:
            msg = f"connect failed rc={rc}"
            if self._replay_store is not None:
                self._replay_store.log_runtime_event("mqtt_connect_failed", {"rc": rc, "message": msg}, level="error")
            self._schedule(self._state_store.set_broker_state("connect_failed", False, msg))

    def _on_disconnect(self, _client, _userdata, rc):
        if self._loop is None:
            return
        status = "reconnecting" if rc != 0 else "disconnected"
        if self._replay_store is not None:
            self._replay_store.log_runtime_event("mqtt_disconnected", {"rc": rc, "status": status}, level="warn" if rc != 0 else "info")
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
        normalized = self._telemetry_normalizer(payload, self._backend_resolver())
        await self._state_store.set_telemetry(normalized)
        if self._replay_store is not None:
            self._replay_store.log_telemetry(normalized)
        snapshot = await self._state_store.snapshot()
        await self._ws_manager.broadcast({
            "type": "telemetry",
            "data": normalized,
            "broker": snapshot["broker"],
        })

    async def _handle_camera(self, frame: dict[str, Any]) -> None:
        await self._state_store.set_video_frame(frame)
        if self._replay_store is not None:
            self._replay_store.log_camera_timing(
                pts=float(frame.get("timestamp") or time.time()),
                frame_index=int(frame.get("frame_index")) if isinstance(frame.get("frame_index"), int) else None,
                meta={"mime_type": frame.get("mime_type"), "bytes": len(frame.get("data", ""))},
            )
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

    async def _presence_loop(self) -> None:
        while self._started:
            try:
                await self.publish_presence_snapshot()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Presence publish failed")
            await asyncio.sleep(PRESENCE_PUBLISH_INTERVAL_S)

    def _gcs_id(self) -> str:
        return (self._cfg.get("client_id") or "gcs-web").strip()

    def _presence_topic(self) -> str:
        topic = _topic_join(
            self._cfg.get("topic_prefix", ""),
            self._cfg.get("gcs_presence_topic", "gcs/presence"),
        ).rstrip("/")
        return f"{topic}/{self._gcs_id()}"

    def _presence_payload(
        self,
        active: bool,
        browser_count: int = 0,
        active_controller_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "gcs_id": self._gcs_id(),
            "active": bool(active),
            "timestamp": time.time(),
            "browser_count": int(browser_count),
            "active_controller_id": active_controller_id,
        }
