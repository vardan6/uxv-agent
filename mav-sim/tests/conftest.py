"""Test bootstrap for the `mav-sim/` suite.

`mav-sim`'s modules (`config.py`, `transport_manager.py`, `mavlink_listener.py`,
`grpc_service.py`, `app.py`) import each other with flat, top-level names
(`import config`, `import mavlink_listener`) rather than as a package, matching
how `run.sh` launches `app.py` directly from within `mav-sim/`. Insert the
`mav-sim/` directory onto `sys.path` so the test suite can import them the
same way, without turning `mav-sim/` into an installable package.
"""

from __future__ import annotations

import sys
from pathlib import Path

MAV_SIM_DIR = Path(__file__).resolve().parent.parent
if str(MAV_SIM_DIR) not in sys.path:
    sys.path.insert(0, str(MAV_SIM_DIR))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_mavlink_listener_module_state():
    """`mavlink_listener` keeps mission-upload state in module globals.

    Reset them before and after every test so tests can run in any order
    without leaking an in-progress mission upload or a stale MAVLink
    connection handle into the next test.
    """
    import mavlink_listener

    def _reset():
        mavlink_listener._upload_state.clear()
        mavlink_listener._upload_state.update(
            active=False, expected=0, items={}, src_sys=0, src_comp=0,
        )
        mavlink_listener._conn = None

    _reset()
    yield
    _reset()
