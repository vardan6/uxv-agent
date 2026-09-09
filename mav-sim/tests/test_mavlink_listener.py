"""TA6 — MAVLink mission upload protocol transitions.

Exercises `mavlink_listener._handle_protocol` (the MISSION_COUNT /
MISSION_ITEM_INT / MISSION_ACK state machine) against a fake MAVLink
connection — no real socket, no pymavlink connection object required.
"""

from __future__ import annotations

from typing import Any

import mavlink_listener as ml


class _FakeMsg:
    def __init__(self, msg_type: str, **fields: Any) -> None:
        self._type = msg_type
        self._fields = fields
        for key, value in fields.items():
            setattr(self, key, value)

    def get_type(self) -> str:
        return self._type

    def to_dict(self) -> dict[str, Any]:
        return {"mavpackettype": self._type, **self._fields}

    def get_srcSystem(self) -> int:
        return self._fields.get("_src_sys", 7)

    def get_srcComponent(self) -> int:
        return self._fields.get("_src_comp", 1)


class _FakeMav:
    def __init__(self) -> None:
        self.mission_ack_calls: list[tuple] = []
        self.mission_request_int_calls: list[tuple] = []

    def mission_ack_send(self, *args, **kwargs) -> None:
        self.mission_ack_calls.append((args, kwargs))

    def mission_request_int_send(self, *args, **kwargs) -> None:
        self.mission_request_int_calls.append((args, kwargs))


class _FakeConn:
    def __init__(self) -> None:
        self.mav = _FakeMav()


def test_mission_count_zero_acks_immediately_without_starting_upload():
    conn = _FakeConn()
    msg = _FakeMsg("MISSION_COUNT", count=0, _src_sys=7, _src_comp=1)

    ml._handle_protocol(conn, msg)

    assert conn.mav.mission_ack_calls == [((7, 1, 0), {"mission_type": 0})]
    assert ml._upload_state["active"] is False


def test_mission_count_nonzero_starts_upload_and_requests_first_item():
    conn = _FakeConn()
    msg = _FakeMsg("MISSION_COUNT", count=2, _src_sys=7, _src_comp=1)

    ml._handle_protocol(conn, msg)

    assert ml._upload_state["active"] is True
    assert ml._upload_state["expected"] == 2
    assert ml._upload_state["items"] == {}
    assert conn.mav.mission_request_int_calls == [((7, 1, 0), {"mission_type": 0})]


def test_mission_item_int_out_of_order_before_count_is_ignored():
    """A MISSION_ITEM_INT arriving with no active upload must not be stored —
    the "out-of-sequence protocol message" boundary from the audit."""
    conn = _FakeConn()
    msg = _FakeMsg(
        "MISSION_ITEM_INT", seq=0, x=100000000, y=200000000, z=15.0,
        command=16, _src_sys=7, _src_comp=1,
    )

    ml._handle_protocol(conn, msg)

    assert ml.get_mission() == {"count": 0, "items": []}


def test_full_mission_upload_lifecycle_computes_lat_lon_and_acks_on_completion():
    conn = _FakeConn()
    ml._handle_protocol(conn, _FakeMsg("MISSION_COUNT", count=2, _src_sys=7, _src_comp=1))

    item0 = _FakeMsg(
        "MISSION_ITEM_INT", seq=0, x=473977420, y=-1224375500, z=15.0,
        command=16, _src_sys=7, _src_comp=1,
    )
    ml._handle_protocol(conn, item0)

    # Mid-upload: the next item must have been requested, not acked yet.
    assert ml._upload_state["active"] is True
    assert len(conn.mav.mission_request_int_calls) == 2  # seq 0 request + seq 1 request
    assert conn.mav.mission_ack_calls == []

    item1 = _FakeMsg(
        "MISSION_ITEM_INT", seq=1, x=473980000, y=-1224380000, z=20.0,
        command=16, _src_sys=7, _src_comp=1,
    )
    ml._handle_protocol(conn, item1)

    assert ml._upload_state["active"] is False
    assert conn.mav.mission_ack_calls == [((7, 1, 0), {"mission_type": 0})]

    mission = ml.get_mission()
    assert mission["count"] == 2
    first = mission["items"][0]
    assert first["_lat"] == 473977420 / 1e7
    assert first["_lon"] == -1224375500 / 1e7
    assert first["_alt"] == 15.0


def test_mission_item_uses_float_fields_directly_not_scaled():
    conn = _FakeConn()
    ml._handle_protocol(conn, _FakeMsg("MISSION_COUNT", count=1, _src_sys=7, _src_comp=1))

    item = _FakeMsg(
        "MISSION_ITEM", seq=0, x=47.397, y=-122.437, z=12.5,
        command=16, _src_sys=7, _src_comp=1,
    )
    ml._handle_protocol(conn, item)

    mission = ml.get_mission()
    assert mission["items"][0]["_lat"] == 47.397
    assert mission["items"][0]["_lon"] == -122.437


def test_get_mission_reflects_module_state_snapshot():
    assert ml.get_mission() == {"count": 0, "items": []}
