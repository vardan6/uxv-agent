"""Tier 0 measurement harness — five agent surfaces.

Prints sizes for default (no optional sources) and all-on (all source controls
enabled) configurations. Run from gcs_server/:

    python -m tools.measure_agent_surfaces
"""
from __future__ import annotations

import json
from typing import Any

from ai.context_service import (
    _CONTEXT_BUDGET_CHARS_DEFAULT,
    _CONTEXT_BUDGET_CHARS_MIN,
    _CONTEXT_BUDGET_CHARS_MAX,
)
from ai.data_access import build_data_access_manifest
from ai.execution_mode import execution_tools_for_mode
from ai.tool_registry import (
    EXECUTION,
    DEFAULT_PERMISSIONS,
    _OPTIONAL_TOOL_NAMES_BY_SOURCE,
    ToolRegistry,
    allowed_tool_names_for_source_controls,
)

_CHARS_PER_TOKEN = 4  # rough estimate used throughout


def _tok(chars: int) -> str:
    return f"~{chars // _CHARS_PER_TOKEN} tok"


def _surface_1(registry: ToolRegistry) -> None:
    defs = registry.definitions()
    registered = len(defs)

    def_sc: dict[str, bool] = {}
    all_sc = {key: True for key in _OPTIONAL_TOOL_NAMES_BY_SOURCE}

    allowed_default = allowed_tool_names_for_source_controls(def_sc)
    allowed_all = allowed_tool_names_for_source_controls(all_sc)

    # Non-execution tools: pass permission filter (DEFAULT_PERMISSIONS) but not
    # the DISABLED_PERMISSIONS gate (no COMMAND_STAGING tools currently).
    non_exec = {d.name for d in defs if d.permission != EXECUTION}

    print("=== Surface 1: Tool Counts ===")
    print(f"  Registered (all definitions):            {registered}")
    print(f"  Source-control-allowed (default):        {len(allowed_default)}")
    print(f"  Source-control-allowed (all-on):         {len(allowed_all)}")
    print()
    print("  Execution-mode binding (no src-control gate — typical agent path):")
    for mode in ("strict", "confirm", "autonomous"):
        exec_bound = execution_tools_for_mode(mode)
        bound = non_exec | exec_bound
        print(f"    {mode:12s}: {len(bound)} tools ({len(non_exec)} non-exec + {len(exec_bound)} exec)")
    print()


def _serialize_tool(tool: Any) -> dict[str, Any]:
    name = str(getattr(tool, "name", ""))
    description = str(getattr(tool, "description", ""))
    args_schema = getattr(tool, "args_schema", None)
    schema: dict[str, Any] = {}
    if args_schema is not None:
        try:
            schema = args_schema.model_json_schema()
        except AttributeError:
            try:
                schema = args_schema.schema()
            except Exception:
                pass
    return {"name": name, "description": description, "input_schema": schema}


def _build_tools(
    registry: ToolRegistry,
    allowed: set[str] | None,
    *,
    include_execution: bool = True,
) -> list[Any]:
    permissions = set(DEFAULT_PERMISSIONS) | ({EXECUTION} if include_execution else set())
    tools = registry.build_langchain_tools(None, {}, permissions=permissions)
    if allowed is not None:
        tools = [t for t in tools if str(getattr(t, "name", "")) in allowed]
    return tools


def _surface_2(registry: ToolRegistry) -> None:
    try:
        def_sc: dict[str, bool] = {}
        all_sc = {key: True for key in _OPTIONAL_TOOL_NAMES_BY_SOURCE}
        allowed_default = allowed_tool_names_for_source_controls(def_sc)
        allowed_all = allowed_tool_names_for_source_controls(all_sc)

        tools_default = _build_tools(registry, allowed_default)
        tools_all = _build_tools(registry, allowed_all)

        for label, tools in (("default", tools_default), ("all-on", tools_all)):
            schemas = [_serialize_tool(t) for t in tools]
            payload = json.dumps(schemas, separators=(",", ":"))
            b = len(payload.encode())
            print(f"=== Surface 2: Provider Tool-Schema Size ({label}) ===")
            print(f"  Tools bound: {len(tools)}")
            print(f"  JSON bytes:  {b:,}")
            print(f"  Estimated:   {_tok(b)}")
            print()
    except Exception as exc:
        print(f"=== Surface 2: Provider Tool-Schema Size ===\n  [SKIP — {exc}]\n")


def _surface_3_4(registry: ToolRegistry) -> None:
    from ai.chat_service import _data_access_manifest_prompt, _tool_catalog_prompt

    def_sc: dict[str, bool] = {}
    all_sc = {key: True for key in _OPTIONAL_TOOL_NAMES_BY_SOURCE}
    allowed_default = allowed_tool_names_for_source_controls(def_sc)
    allowed_all = allowed_tool_names_for_source_controls(all_sc)

    defs = registry.definitions()

    try:
        tools_default = _build_tools(registry, allowed_default, include_execution=False)
        tools_all = _build_tools(registry, allowed_all, include_execution=False)
    except Exception as exc:
        print(f"=== Surface 3/4 ===\n  [SKIP — {exc}]\n")
        return

    manifest_default = build_data_access_manifest(defs, allowed_tool_names=allowed_default)
    manifest_all = build_data_access_manifest(defs, allowed_tool_names=allowed_all)

    p3_default = _tool_catalog_prompt(tools_default)
    p3_all = _tool_catalog_prompt(tools_all)
    p4_default = _data_access_manifest_prompt(manifest_default)
    p4_all = _data_access_manifest_prompt(manifest_all)

    print("=== Surface 3: Tool-Name List Prompt (_tool_catalog_prompt) ===")
    print(f"  default: {len(p3_default):>5} chars  {_tok(len(p3_default))}")
    print(f"  all-on:  {len(p3_all):>5} chars  {_tok(len(p3_all))}")
    print()
    print("=== Surface 4: Data-Surface Manifest Prompt (_data_access_manifest_prompt) ===")
    print(f"  default: {len(p4_default):>5} chars  {_tok(len(p4_default))}")
    print(f"  all-on:  {len(p4_all):>5} chars  {_tok(len(p4_all))}")
    print()


def _surface_5() -> None:
    print("=== Surface 5: Compact Context Block (context_snapshot.prompt) ===")
    print(f"  Default budget: {_CONTEXT_BUDGET_CHARS_DEFAULT:,} chars  {_tok(_CONTEXT_BUDGET_CHARS_DEFAULT)}")
    print(f"  Range:          {_CONTEXT_BUDGET_CHARS_MIN:,} – {_CONTEXT_BUDGET_CHARS_MAX:,} chars")
    print(f"  Note: actual prompt size requires a live runtime; measure via a real agent run.")
    print()


def main() -> None:
    registry = ToolRegistry()
    _surface_1(registry)
    _surface_2(registry)
    _surface_3_4(registry)
    _surface_5()


if __name__ == "__main__":
    main()
