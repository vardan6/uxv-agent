"""Shared `AppRuntime` test double.

`AppRuntime` (`gcs_server/runtime.py`) is a fully-typed dataclass — every
field is always populated in production. Production code (`agent_loop.py`,
`mission_control.py`, `mission_execution_session.py`, `routers/ai.py`) used
`getattr(runtime, "x", None)` defensively only because tests built ad hoc,
partial `SimpleNamespace` runtime doubles. `make_stub_runtime` builds one with
every `AppRuntime` field present (defaulting to `None`), so callers can use
direct attribute access and tests only override the fields they exercise.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

_APP_RUNTIME_FIELDS = (
    "config",
    "state_store",
    "ws_manager",
    "mqtt_runtime",
    "control_service",
    "replay_store",
    "replay_analytics",
    "ai_store",
    "mission_execution_service",
    "mission_store",
    "operational_constraints_store",
    "secret_store",
    "ai_executor",
    "mission_execution_sessions",
)

# Not a dataclass field, but a real bound-method attribute every AppRuntime
# instance carries; tests override it with a fake coroutine.
_APP_RUNTIME_METHODS = ("reconfigure_mqtt",)

_APP_RUNTIME_ATTRS = frozenset(_APP_RUNTIME_FIELDS + _APP_RUNTIME_METHODS)


def make_stub_runtime(**overrides: Any) -> SimpleNamespace:
    unknown = set(overrides) - _APP_RUNTIME_ATTRS
    if unknown:
        raise TypeError(f"make_stub_runtime got unknown AppRuntime attribute(s): {sorted(unknown)}")
    fields = dict.fromkeys(_APP_RUNTIME_FIELDS, None)
    fields.update(overrides)
    return SimpleNamespace(**fields)
