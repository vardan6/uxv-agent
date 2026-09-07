import asyncio
import queue
import threading
from datetime import datetime, timezone

from pymavlink import mavutil

import config

_q: queue.Queue = queue.Queue(maxsize=config.QUEUE_MAXSIZE)
_conn = None
_send_lock = threading.Lock()

_upload_state: dict = {
    "active": False,
    "expected": 0,
    "items": {},
    "src_sys": 0,
    "src_comp": 0,
}

_MAV_CMD_NAMES = {
    16: "NAV_WAYPOINT",
    17: "NAV_LOITER_UNLIM",
    18: "NAV_LOITER_TURNS",
    19: "NAV_LOITER_TIME",
    20: "NAV_RETURN_TO_LAUNCH",
    21: "NAV_LAND",
    22: "NAV_TAKEOFF",
    300: "MISSION_START",
}

_MISSION_ACK_TYPES = {
    0: "ACCEPTED",
    1: "ERROR",
    2: "UNSUPPORTED_FRAME",
    3: "COORDINATES_OUT_OF_RANGE",
    4: "X_LAN_OUT_OF_RANGE",
    5: "Y_LAN_OUT_OF_RANGE",
    6: "Z_OUT_OF_RANGE",
    7: "NO_SPACE",
    8: "INVALID_SEQUENCE",
    9: "DENIED",
    10: "OPERATION_CANCELLED",
}


def get_queue() -> queue.Queue:
    return _q


def get_mission() -> dict:
    return {
        "count": len(_upload_state["items"]),
        "items": list(_upload_state["items"].values()),
    }


def _cmd_name(cmd: int) -> str:
    return _MAV_CMD_NAMES.get(cmd, str(cmd))


def _summarise(msg) -> str:
    t = msg.get_type()

    if t == "HEARTBEAT":
        return f"type={msg.type}  autopilot={msg.autopilot}  status={msg.system_status}"

    if t == "MISSION_COUNT":
        return f"count={msg.count}  target_sys={msg.target_system}  target_comp={msg.target_component}"

    if t in ("MISSION_REQUEST", "MISSION_REQUEST_INT"):
        return f"seq={msg.seq}  target_sys={msg.target_system}  target_comp={msg.target_component}"

    if t == "MISSION_ITEM_INT":
        lat = msg.x / 1e7
        lon = msg.y / 1e7
        return (
            f"seq={msg.seq}  cmd={msg.command} ({_cmd_name(msg.command)})"
            f"  lat={lat:.6f}  lon={lon:.6f}  alt={msg.z:.1f}m"
        )

    if t == "MISSION_ITEM":
        return (
            f"seq={msg.seq}  cmd={msg.command} ({_cmd_name(msg.command)})"
            f"  lat={msg.x:.6f}  lon={msg.y:.6f}  alt={msg.z:.1f}m"
        )

    if t == "MISSION_ACK":
        label = _MISSION_ACK_TYPES.get(msg.type, str(msg.type))
        return f"type={msg.type} ({label})"

    if t == "COMMAND_LONG":
        return (
            f"cmd={msg.command} ({_cmd_name(msg.command)})"
            f"  p1={msg.param1}  p2={msg.param2}"
        )

    if t == "SET_MODE":
        return f"base_mode={msg.base_mode}  custom_mode={msg.custom_mode}"

    if t == "GLOBAL_POSITION_INT":
        lat = msg.lat / 1e7
        lon = msg.lon / 1e7
        alt = msg.alt / 1e3
        return f"lat={lat:.6f}  lon={lon:.6f}  alt={alt:.1f}m  hdg={msg.hdg / 100:.1f}°"

    fields = {
        k: v
        for k, v in msg.to_dict().items()
        if not k.startswith("_") and k not in ("mavpackettype",)
    }
    return "  ".join(f"{k}={v}" for k, v in list(fields.items())[:6])


def _handle_protocol(conn, msg):
    """Auto-respond to MAVLink mission upload protocol (Phase 3)."""
    t = msg.get_type()

    if t == "MISSION_COUNT":
        if msg.count == 0:
            with _send_lock:
                conn.mav.mission_ack_send(
                    msg.get_srcSystem(), msg.get_srcComponent(), 0, mission_type=0
                )
            return
        _upload_state.update(
            active=True,
            expected=msg.count,
            items={},
            src_sys=msg.get_srcSystem(),
            src_comp=msg.get_srcComponent(),
        )
        with _send_lock:
            conn.mav.mission_request_int_send(
                _upload_state["src_sys"], _upload_state["src_comp"], 0, mission_type=0
            )

    elif t in ("MISSION_ITEM_INT", "MISSION_ITEM") and _upload_state["active"]:
        fields = {
            k: v
            for k, v in msg.to_dict().items()
            if not k.startswith("_") and k != "mavpackettype"
        }
        # Pre-compute WGS84 lat/lon for telemetry simulation (Phase 4).
        # MISSION_ITEM_INT stores lat/lon as int32 × 1e7; MISSION_ITEM uses float.
        if t == "MISSION_ITEM_INT":
            fields["_lat"] = msg.x / 1e7
            fields["_lon"] = msg.y / 1e7
            fields["_alt"] = float(msg.z)
        else:
            fields["_lat"] = float(msg.x)
            fields["_lon"] = float(msg.y)
            fields["_alt"] = float(msg.z)
        _upload_state["items"][msg.seq] = fields
        nxt = msg.seq + 1
        with _send_lock:
            if nxt < _upload_state["expected"]:
                conn.mav.mission_request_int_send(
                    _upload_state["src_sys"], _upload_state["src_comp"], nxt, mission_type=0
                )
            else:
                conn.mav.mission_ack_send(
                    _upload_state["src_sys"], _upload_state["src_comp"],
                    0,  # MAV_MISSION_RESULT_ACCEPTED
                    mission_type=0,
                )
                _upload_state["active"] = False


async def simulate_execution(broadcast_fn, interval: float = 2.0):
    """Simulate FC execution: emit GLOBAL_POSITION_INT + MISSION_ITEM_REACHED per waypoint."""
    items = _upload_state["items"]
    if not items:
        return
    for seq in sorted(items.keys()):
        item = items[seq]
        lat = item.get("_lat", 0.0)
        lon = item.get("_lon", 0.0)
        alt = item.get("_alt", 0.0)

        with _send_lock:
            if _conn is not None:
                _conn.mav.global_position_int_send(
                    0,               # time_boot_ms
                    int(lat * 1e7),  # lat degE7
                    int(lon * 1e7),  # lon degE7
                    int(alt * 1000), # alt mm ASL
                    int(alt * 1000), # relative_alt mm
                    0, 0, 0,         # vx, vy, vz cm/s
                    0,               # hdg cdeg (unknown)
                )
                _conn.mav.mission_item_reached_send(seq)

        now = datetime.now(timezone.utc)
        ts = now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"
        await broadcast_fn({
            "ts": ts, "type": "GLOBAL_POSITION_INT",
            "summary": f"lat={lat:.6f}  lon={lon:.6f}  alt={alt:.1f}m",
            "sys": 1, "comp": 0,
            "fields": {"lat_degE7": int(lat * 1e7), "lon_degE7": int(lon * 1e7), "alt_mm": int(alt * 1000)},
        })
        await broadcast_fn({
            "ts": ts, "type": "MISSION_ITEM_REACHED",
            "summary": f"seq={seq}",
            "sys": 1, "comp": 0,
            "fields": {"seq": seq},
        })
        await asyncio.sleep(interval)


def _listen():
    global _conn
    conn_str = f"udpin:{config.MAVLINK_HOST}:{config.MAVLINK_PORT}"
    _conn = mavutil.mavlink_connection(conn_str, dialect=config.MAVLINK_DIALECT, source_system=1)

    while True:
        msg = _conn.recv_match(blocking=True, timeout=1.0)
        if msg is None:
            continue
        if msg.get_type() == "BAD_DATA":
            continue

        _handle_protocol(_conn, msg)

        now = datetime.now(timezone.utc)
        fields = {
            k: v
            for k, v in msg.to_dict().items()
            if not k.startswith("_") and k not in ("mavpackettype",)
        }
        entry = {
            "ts": now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}",
            "type": msg.get_type(),
            "summary": _summarise(msg),
            "sys": msg.get_srcSystem(),
            "comp": msg.get_srcComponent(),
            "fields": fields,
        }

        try:
            _q.put_nowait(entry)
        except queue.Full:
            try:
                _q.get_nowait()
            except queue.Empty:
                pass
            _q.put_nowait(entry)


def start():
    t = threading.Thread(target=_listen, daemon=True, name="mavlink-listener")
    t.start()
