"""TA7 — bounded WebSocket behavior (audit item 7, narrow slice).

`WebSocketManager` fans out `broadcast`/`broadcast_to_subscribers` to every
connected client sequentially. A client whose `send_json` raises (closed
socket, slow/broken pipe) must not stop delivery to the remaining clients,
and must be pruned from both the socket table and its subscriptions rather
than accumulating as dead state.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ws import WebSocketManager


class FailingWebSocket:
    async def accept(self) -> None:
        return None

    async def send_json(self, message: dict[str, Any]) -> None:
        raise ConnectionResetError("client went away")


class RecordingWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def accept(self) -> None:
        return None

    async def send_json(self, message: dict[str, Any]) -> None:
        self.messages.append(message)


def test_broadcast_reaches_healthy_clients_despite_one_failing_client() -> None:
    async def run() -> None:
        manager = WebSocketManager()
        healthy = RecordingWebSocket()
        failing = FailingWebSocket()
        await manager.connect("healthy", healthy)  # type: ignore[arg-type]
        await manager.connect("failing", failing)  # type: ignore[arg-type]

        await manager.broadcast({"type": "telemetry", "data": {"n": 1}})

        assert healthy.messages == [{"type": "telemetry", "data": {"n": 1}}]
        assert await manager.connection_count() == 1

    asyncio.run(run())


def test_failing_client_is_pruned_from_subscriptions_too() -> None:
    async def run() -> None:
        manager = WebSocketManager()
        failing = FailingWebSocket()
        await manager.connect("failing", failing)  # type: ignore[arg-type]
        await manager.subscribe("failing", "video/default")

        await manager.broadcast_to_subscribers(
            "video/default", {"type": "video_frame", "data": {"frame": 1}}
        )

        assert await manager.subscribers_for("video/default") == set()
        assert await manager.connection_count() == 0

    asyncio.run(run())


def test_send_to_unknown_client_is_a_silent_no_op() -> None:
    async def run() -> None:
        manager = WebSocketManager()
        # No connect() call for "ghost" — must not raise (e.g. a stale
        # client_id after disconnect racing with an in-flight send).
        await manager.send("ghost", {"type": "pong"})

    asyncio.run(run())


def test_disconnect_is_idempotent_for_an_unknown_client() -> None:
    async def run() -> None:
        manager = WebSocketManager()
        # Disconnecting a client that was never connected (or already
        # disconnected) must not raise.
        await manager.disconnect("never-connected")

    asyncio.run(run())
