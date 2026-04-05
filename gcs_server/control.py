from __future__ import annotations

import asyncio
import time
from typing import Any


class ControlService:
    def __init__(self, publish_func, controller_store, control_hz: int):
        self._publish_func = publish_func
        self._controller_store = controller_store
        self._control_hz = max(1, int(control_hz))
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

    async def set_buttons(self, client_id: str, buttons: dict[str, Any]) -> bool:
        if not await self._controller_store.renew_controller(client_id):
            return False
        async with self._lock:
            self._owner_client_id = client_id
            for name in self._buttons:
                if name in buttons:
                    self._buttons[name] = bool(buttons[name])
            self._pending_neutral = True
        return True

    async def clear_buttons(self, client_id: str) -> None:
        async with self._lock:
            if self._owner_client_id != client_id:
                return
            for name in self._buttons:
                self._buttons[name] = False
            self._pending_neutral = True

    async def _run(self) -> None:
        period = 1.0 / self._control_hz
        while self._running:
            frame = None
            async with self._lock:
                active = any(self._buttons.values())
                owner = self._owner_client_id
                if active or self._pending_neutral:
                    frame = {
                        "mode": "digital",
                        "buttons": dict(self._buttons),
                        "source": f"gcs:{owner}" if owner else "gcs",
                        "timestamp": time.time(),
                    }
                    if not active:
                        self._pending_neutral = False
            if frame is not None:
                if owner:
                    await self._controller_store.renew_controller(owner)
                await self._publish_func(frame)
            await asyncio.sleep(period)
