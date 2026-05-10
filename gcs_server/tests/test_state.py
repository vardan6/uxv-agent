from __future__ import annotations

import asyncio
from unittest.mock import patch

from state import CONTROLLER_STALE_SECONDS, LocalStateBackend


def test_try_claim_controller_rejects_active_other_client_until_stale() -> None:
    store = LocalStateBackend(telemetry_stale_ms=1000)

    with patch("state.time.time", return_value=100.0):
        assert asyncio.run(store.try_claim_controller("client-a")) is True

    with patch("state.time.time", return_value=100.5):
        assert asyncio.run(store.try_claim_controller("client-b")) is False

    with patch("state.time.time", return_value=100.5 + CONTROLLER_STALE_SECONDS):
        assert asyncio.run(store.try_claim_controller("client-b")) is True
