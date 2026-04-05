from __future__ import annotations

import asyncio
import copy
from typing import Any

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._sockets: dict[str, WebSocket] = {}

    async def connect(self, client_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._sockets[client_id] = websocket

    async def disconnect(self, client_id: str) -> None:
        async with self._lock:
            self._sockets.pop(client_id, None)

    async def send(self, client_id: str, message: dict[str, Any]) -> None:
        async with self._lock:
            ws = self._sockets.get(client_id)
        if ws is None:
            return
        await ws.send_json(copy.deepcopy(message))

    async def broadcast(self, message: dict[str, Any]) -> None:
        async with self._lock:
            sockets = list(self._sockets.items())
        stale_ids: list[str] = []
        payload = copy.deepcopy(message)
        for client_id, ws in sockets:
            try:
                await ws.send_json(payload)
            except Exception:
                stale_ids.append(client_id)
        if stale_ids:
            async with self._lock:
                for client_id in stale_ids:
                    self._sockets.pop(client_id, None)
