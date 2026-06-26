from __future__ import annotations

import asyncio
from typing import Any

from gcs_server.ws import WebSocketManager


class FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.messages: list[dict[str, Any]] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, message: dict[str, Any]) -> None:
        self.messages.append(message)


def test_subscribe_unsubscribe_filters_broadcasts() -> None:
    async def run() -> None:
        manager = WebSocketManager()
        subscribed = FakeWebSocket()
        unsubscribed = FakeWebSocket()
        await manager.connect("client-a", subscribed)  # type: ignore[arg-type]
        await manager.connect("client-b", unsubscribed)  # type: ignore[arg-type]

        await manager.subscribe("client-a", "video/default")
        await manager.broadcast_to_subscribers(
            "video/default",
            {"type": "video_frame", "topic": "video/default", "data": {"frame": 1}},
        )

        assert subscribed.messages == [
            {"type": "video_frame", "topic": "video/default", "data": {"frame": 1}},
        ]
        assert unsubscribed.messages == []

        await manager.unsubscribe("client-a", "video/default")
        await manager.broadcast_to_subscribers(
            "video/default",
            {"type": "video_frame", "topic": "video/default", "data": {"frame": 2}},
        )

        assert subscribed.messages == [
            {"type": "video_frame", "topic": "video/default", "data": {"frame": 1}},
        ]

    asyncio.run(run())


def test_snapshot_topics_are_available_without_video_subscription() -> None:
    async def run() -> None:
        manager = WebSocketManager()
        client = FakeWebSocket()
        await manager.connect("client-a", client)  # type: ignore[arg-type]

        await manager.send(
            "client-a",
            {
                "type": "snapshot",
                "data": {"video": {"enabled": True, "latest_frame": {"frame": 1}}},
            },
        )

        assert client.messages == [
            {
                "type": "snapshot",
                "data": {"video": {"enabled": True, "latest_frame": {"frame": 1}}},
            },
        ]
        assert await manager.subscribers_for("video/default") == set()

    asyncio.run(run())
