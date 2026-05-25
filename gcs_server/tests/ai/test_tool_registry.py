from __future__ import annotations

from ai.tool_registry import TOOL_CONTRACTS, ToolRegistry


def test_planner_loop_tools_have_applied_contracts() -> None:
    registry = ToolRegistry()
    definitions = {definition.name: definition for definition in registry.definitions()}

    expected_tools = {
        "parse_rover_intent",
        "lazy_load_replay",
        "lazy_load_ai_memory",
        "lazy_load_settings",
        "lazy_load_sensor",
        "request_clarification",
    }

    for name in expected_tools:
        definition = definitions[name]
        contract = TOOL_CONTRACTS[name]

        assert definition.contract == contract
        assert definition.input_schema == contract["inputs"]
        assert definition.output_schema == contract["returns"]
