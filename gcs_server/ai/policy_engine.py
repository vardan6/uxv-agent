from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .tool_registry import DISABLED_PERMISSIONS, ToolDefinition


POLICY_DENIED_STOP_REASON = "policy_denied"

# EXECUTION is tier 4. Agent runs may reach it (the per-mode tool binding
# decides whether any execution tool is actually present); plain chat stays
# capped at PLANNING (tier 2). COMMAND_STAGING (tier 3) remains blocked by
# DISABLED_PERMISSIONS regardless of this cap.
_RUN_MODE_MAX_TIER = {
    "chat": 2,
    "agent": 4,
}


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    action: str
    reason: str
    stop_reason: str
    tool_name: str
    permission: str
    tier: int
    required_scopes: tuple[str, ...]
    side_effects: tuple[str, ...]

    def as_trace_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "stop_reason": self.stop_reason,
            "tool_name": self.tool_name,
            "permission": self.permission,
            "tier": self.tier,
            "required_scopes": list(self.required_scopes),
            "side_effects": list(self.side_effects),
        }


class PolicyEngine:
    """Thin tool-call policy seam for the shared agent runtime.

    Phase 3 keeps behavior intentionally narrow: evaluate known tool metadata,
    enforce enabled permissions, verify tier/scopes against the current run,
    and leave higher-tier grants / budgets for later phases.
    """

    def evaluate(
        self,
        *,
        definition: ToolDefinition | None,
        tool_name: str,
        available_permissions: frozenset[str],
        granted_scopes: frozenset[str] | None = None,
        run_mode: str = "agent",
    ) -> PolicyDecision:
        if definition is None:
            return self._deny(tool_name, "tool is not registered")

        if definition.permission in DISABLED_PERMISSIONS:
            return self._deny(definition.name, f"permission '{definition.permission}' is disabled", definition)

        if definition.permission not in available_permissions:
            return self._deny(definition.name, f"permission '{definition.permission}' is not allowed", definition)

        max_tier = _RUN_MODE_MAX_TIER.get(str(run_mode or "").strip().lower(), 2)
        if definition.tier > max_tier:
            return self._deny(
                definition.name,
                f"tier {definition.tier} exceeds run-mode limit {max_tier}",
                definition,
            )

        required_scopes = definition.required_scopes
        active_scopes = granted_scopes or frozenset()
        if required_scopes and not required_scopes.issubset(active_scopes):
            missing = sorted(required_scopes.difference(active_scopes))
            return self._deny(definition.name, f"missing required scopes: {', '.join(missing)}", definition)

        return PolicyDecision(
            action="allow",
            reason="allowed by current policy",
            stop_reason="",
            tool_name=definition.name,
            permission=definition.permission,
            tier=definition.tier,
            required_scopes=tuple(sorted(definition.required_scopes)),
            side_effects=tuple(sorted(definition.side_effects)),
        )

    def _deny(
        self,
        tool_name: str,
        reason: str,
        definition: ToolDefinition | None = None,
    ) -> PolicyDecision:
        return PolicyDecision(
            action="deny",
            reason=reason,
            stop_reason=POLICY_DENIED_STOP_REASON,
            tool_name=tool_name,
            permission=definition.permission if definition else "",
            tier=int(definition.tier) if definition else -1,
            required_scopes=tuple(sorted(definition.required_scopes)) if definition else (),
            side_effects=tuple(sorted(definition.side_effects)) if definition else (),
        )
