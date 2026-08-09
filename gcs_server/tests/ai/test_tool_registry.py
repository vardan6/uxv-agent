from __future__ import annotations

from ai.tool_registry import _TOOL_META, ToolRegistry


def test_planner_loop_tools_have_applied_contracts() -> None:
    registry = ToolRegistry()
    definitions = {definition.name: definition for definition in registry.definitions()}

    expected_tools = {
        "parse_rover_intent",
        "lazy_load_replay",
        "lazy_load_ai_memory",
        "lazy_load_settings",
        "lazy_load_sensor",
    }

    for name in expected_tools:
        definition = definitions[name]
        contract = _TOOL_META[name].contract

        assert definition.contract == contract
        assert definition.input_schema == contract["inputs"]
        assert definition.output_schema == contract["returns"]


def test_all_tools_have_contracts() -> None:
    """O9: TOOL_CONTRACTS was a manually-maintained dict a tool could silently
    miss (9 tools had none, including all 4 EXECUTION-tier). Every tool's
    contract now lives inline on its ToolMeta declaration, so this can assert
    universally instead of over a hand-picked subset."""
    registry = ToolRegistry()
    for definition in registry.definitions():
        assert definition.contract, f"{definition.name} has no contract"
        assert definition.contract.get("returns"), f"{definition.name} has no returns contract"
