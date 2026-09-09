"""TA6 — API and WebSocket state via `app.py`.

Uses `fastapi.testclient.TestClient` *without* entering it as a context
manager, which means Starlette never fires the `@app.on_event("startup")`
handler. That's intentional: startup calls `transport_manager.start()` and
`mavlink_listener.start()`, which open a real UDP socket and a daemon
listener thread — exactly the real hardware/network the audit says this
suite must avoid. Route handlers and the WebSocket endpoint don't depend on
startup having run, so this exercises the real API surface without it.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import app as app_module
import mavlink_listener as ml


def _client() -> TestClient:
    return TestClient(app_module.app)


def test_api_mission_reflects_current_mission_state():
    client = _client()

    response = client.get("/api/mission")

    assert response.status_code == 200
    assert response.json() == {"count": 0, "items": []}


def test_api_mission_reports_uploaded_items():
    ml._upload_state["items"] = {0: {"seq": 0, "_lat": 1.0, "_lon": 2.0, "_alt": 3.0}}
    client = _client()

    response = client.get("/api/mission")

    assert response.status_code == 200
    assert response.json()["count"] == 1


def test_api_transports_returns_stable_shape_for_all_three_services():
    client = _client()

    response = client.get("/api/transports")

    assert response.status_code == 200
    body = response.json()
    names = {service["name"] for service in body["services"]}
    assert names == {"mavlink_udp", "mavsdk_grpc", "ros2_mavros"}
    for service in body["services"]:
        assert {"name", "enabled", "state", "summary", "details"} <= service.keys()


def test_api_simulate_returns_started_status_with_requested_interval():
    client = _client()

    response = client.post("/api/simulate", params={"interval": 0.01})

    assert response.status_code == 200
    assert response.json() == {"status": "started", "interval": 0.01}


def test_websocket_connect_and_disconnect_updates_connection_manager():
    client = _client()

    with client.websocket_connect("/ws"):
        assert len(app_module.manager._clients) == 1

    assert len(app_module.manager._clients) == 0


def test_index_serves_static_html():
    client = _client()

    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
