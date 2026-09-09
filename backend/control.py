from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class ControlService:
    def __init__(self, publish_func, controller_store, control_hz: int, replay_store=None):
        self._publish_func = publish_func
        self._controller_store = controller_store
        self._control_hz = max(1, int(control_hz))
        self._replay_store = replay_store
        self._lock = asyncio.Lock()
        self._buttons = {
            "forward": False,
            "backward": False,
            "left": False,
            "right": False,
            "stop": False,
            "camera_toggle": False,
        }
        self._owner_client_id: str | None = None
        self._pending_neutral = False
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="gcs-control-loop")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def update_control_hz(self, control_hz: int) -> None:
        async with self._lock:
            self._control_hz = max(1, int(control_hz))

    async def set_buttons(self, client_id: str, buttons: dict[str, Any]) -> bool:
        if not await self._controller_store.note_controller_input(client_id):
            return False
        frame = None
        async with self._lock:
            self._owner_client_id = client_id
            for name in self._buttons:
                if name in buttons:
                    self._buttons[name] = bool(buttons[name])
            self._pending_neutral = True
            frame = self._build_frame_locked()
        if frame is not None:
            if self._replay_store is not None:
                self._replay_store.log_control(frame, source=f"ws:{client_id}")
            await self._publish_func(frame)
        return True

    async def clear_buttons(self, client_id: str) -> None:
        frame = None
        async with self._lock:
            if self._owner_client_id != client_id:
                return
            for name in self._buttons:
                self._buttons[name] = False
            self._pending_neutral = True
            frame = self._build_frame_locked()
        if frame is not None:
            if self._replay_store is not None:
                self._replay_store.log_control(frame, source=f"ws:{client_id}")
            await self._publish_func(frame)

    def _build_frame_locked(self) -> dict[str, Any] | None:
        active = any(self._buttons.values())
        owner = self._owner_client_id
        if not active and not self._pending_neutral:
            return None
        frame = {
            "mode": "digital",
            "buttons": dict(self._buttons),
            "source": f"gcs:{owner}" if owner else "gcs",
            "timestamp": time.time(),
        }
        if not active:
            self._pending_neutral = False
        return frame

    async def _run(self) -> None:
        while self._running:
            try:
                owner = None
                frame = None
                async with self._lock:
                    owner = self._owner_client_id
                    frame = self._build_frame_locked()
                if frame is not None:
                    if self._replay_store is not None:
                        self._replay_store.log_control(frame, source=f"loop:{owner or 'gcs'}")
                    await self._publish_func(frame)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Control loop publish failed")
            await asyncio.sleep(1.0 / self._control_hz)
