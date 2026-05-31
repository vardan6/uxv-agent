"""ADR 0021 §1 — configurable mission execution modes.

Three modes gate whether the AI may cause rover motion:

| Mode         | AI execute capability                  | Operator action            |
|--------------|----------------------------------------|----------------------------|
| strict       | `execute_mission` not bound            | Manual play only           |
| confirm      | may call `arm_execution`; banner       | `[Play]` on banner < N s   |
| autonomous   | may call `execute_mission` directly    | Watch, can abort           |

`cancel_execution` and `abort` are always bound regardless of mode. The mode
lives under the `mission_lifecycle` settings section; the build-time default is
Autonomous for sim builds and Strict for real-rover builds (ADR 0021 §1).

This module owns mode validation, the build-time default resolver, the
settings-section normalizer, and the mode→execution-tool-binding map. The
execution tools themselves (`arm_execution`, `execute_mission`,
`cancel_execution`, `abort`) land with the Phase 3 server-side executor; until
then the binding map is the forward-looking seam the tool builder consults.
"""

from __future__ import annotations

from typing import Any

STRICT = "strict"
CONFIRM = "confirm"
AUTONOMOUS = "autonomous"
EXECUTION_MODES = (STRICT, CONFIRM, AUTONOMOUS)

# Confirm-mode async banner timeout bounds (ADR 0021 §1 / §6).
CONFIRM_TIMEOUT_MIN_S = 3
CONFIRM_TIMEOUT_MAX_S = 60
CONFIRM_TIMEOUT_DEFAULT_S = 10

# Execution tools that any mode binds. These tools are created with the Phase 3
# executor; the names are fixed here so the binding map is stable in advance.
EXECUTE_MISSION_TOOL = "execute_mission"
ARM_EXECUTION_TOOL = "arm_execution"
# Always bound regardless of mode (ADR 0021 §1).
ALWAYS_BOUND_EXECUTION_TOOLS = frozenset({"cancel_execution", "abort"})

# Sim backends default to Autonomous; anything else (real-rover) defaults to
# Strict. The build-time gate that *enforces* the real-rover default is an open
# question in ADR 0021 — this is the soft default only.
_SIM_BACKENDS = frozenset({"3d-env", "rover-sim-next", "sim", "headless"})


def normalize_mode(value: Any, *, default: str = STRICT) -> str:
    """Coerce an arbitrary value to a valid execution mode, falling back to default."""
    mode = str(value or "").strip().lower()
    return mode if mode in EXECUTION_MODES else default


def normalize_confirm_timeout(value: Any) -> int:
    """Clamp a confirm-banner timeout to the supported [3, 60] s range."""
    try:
        seconds = int(round(float(value)))
    except (TypeError, ValueError):
        return CONFIRM_TIMEOUT_DEFAULT_S
    return max(CONFIRM_TIMEOUT_MIN_S, min(CONFIRM_TIMEOUT_MAX_S, seconds))


def resolve_build_default_mode(config: Any) -> str:
    """Build-time default: Autonomous for sim builds, Strict otherwise."""
    backend = ""
    try:
        backend = str((config.simulation or {}).get("backend") or "").strip().lower()
    except Exception:
        backend = ""
    return AUTONOMOUS if backend in _SIM_BACKENDS else STRICT


def normalize_mission_lifecycle_settings(raw: Any, *, build_default: str = STRICT) -> dict[str, Any]:
    """Normalize the persisted `mission_lifecycle` settings section (ADR 0021 §6).

    `build_default` supplies the execution mode when none is persisted, so a
    fresh config inherits the build-time default rather than a hard-coded value.
    """
    data = raw if isinstance(raw, dict) else {}
    persisted_mode = data.get("execution_mode")
    mode = normalize_mode(persisted_mode, default=normalize_mode(build_default, default=STRICT))
    return {
        "execution_mode": mode,
        "confirm_timeout_s": normalize_confirm_timeout(data.get("confirm_timeout_s")),
        "auto_overlay_new_missions": bool(data.get("auto_overlay_new_missions", True)),
        "steal_map_focus": bool(data.get("steal_map_focus", True)),
        "default_name_template": str(data.get("default_name_template") or "Untitled mission").strip()
        or "Untitled mission",
    }


def resolve_execution_mode(config: Any) -> str:
    """Effective execution mode: persisted value, else the build-time default."""
    build_default = resolve_build_default_mode(config)
    try:
        section = config.mission_lifecycle
    except Exception:
        section = None
    if isinstance(section, dict) and section.get("execution_mode"):
        return normalize_mode(section.get("execution_mode"), default=build_default)
    return build_default


def execution_tools_for_mode(mode: str) -> frozenset[str]:
    """Execution tool names a mode binds to the model (ADR 0021 §1).

    Strict binds neither arm nor execute; Confirm binds `arm_execution`;
    Autonomous binds `execute_mission`. `cancel_execution`/`abort` are always
    included. The tool builder intersects this with the tools that actually
    exist, so naming a not-yet-implemented tool here is a no-op until it lands.
    """
    clean = normalize_mode(mode, default=STRICT)
    bound = set(ALWAYS_BOUND_EXECUTION_TOOLS)
    if clean == CONFIRM:
        bound.add(ARM_EXECUTION_TOOL)
    elif clean == AUTONOMOUS:
        bound.add(EXECUTE_MISSION_TOOL)
    return frozenset(bound)
