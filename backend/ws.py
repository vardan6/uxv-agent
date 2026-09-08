from __future__ import annotations

import asyncio
import copy
from typing import Any

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._sockets: dict[str, WebSocket] = {}
        self._subscriptions: dict[str, set[str]] = {}

    async def connect(self, client_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._sockets[client_id] = websocket
            self._subscriptions[client_id] = set()

    async def disconnect(self, client_id: str) -> None:
        async with self._lock:
            self._sockets.pop(client_id, None)
            self._subscriptions.pop(client_id, None)

    async def connection_count(self) -> int:
        async with self._lock:
            return len(self._sockets)

    async def send(self, client_id: str, message: dict[str, Any]) -> None:
        async with self._lock:
            ws = self._sockets.get(client_id)
        if ws is None:
            return
        await ws.send_json(copy.deepcopy(message))

    async def subscribe(self, client_id: str, topic: str) -> None:
        async with self._lock:
            if client_id not in self._sockets:
                return
            self._subscriptions.setdefault(client_id, set()).add(topic)

    async def unsubscribe(self, client_id: str, topic: str) -> None:
        async with self._lock:
            topics = self._subscriptions.get(client_id)
            if topics is None:
                return
            topics.discard(topic)

    async def subscribers_for(self, topic: str) -> set[str]:
        async with self._lock:
            return {
                client_id
                for client_id, topics in self._subscriptions.items()
                if topic in topics
            }

    async def broadcast(self, message: dict[str, Any]) -> None:
        async with self._lock:
            sockets = list(self._sockets.items())
        await self._send_many(sockets, message)

    async def broadcast_to_subscribers(self, topic: str, message: dict[str, Any]) -> None:
        async with self._lock:
            sockets = [
                (client_id, ws)
                for client_id, ws in self._sockets.items()
                if topic in self._subscriptions.get(client_id, set())
            ]
        await self._send_many(sockets, message)

    async def _send_many(self, sockets: list[tuple[str, WebSocket]], message: dict[str, Any]) -> None:
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
                    self._subscriptions.pop(client_id, None)
