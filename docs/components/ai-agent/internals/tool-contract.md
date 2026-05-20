# Tool Contract Standard (AI Agent Tools)

This document is mandatory for any new or modified agent tool in `ai/tool_registry.py`.

## Required Contract Fields

Every tool must define a contract entry in `TOOL_CONTRACTS` with:

- `inputs`: argument name -> type string
- `required_inputs`: required argument names
- `upstream_from_tools`: which tool outputs can supply required args
- `returns`: returned field -> type string
- `next_tools`: recommended downstream tools for chaining

## Required Implementation Rules

When adding a tool:

1. Add a `ToolDefinition(...)` entry in `_build_definitions`.
2. Set the tool metadata fields on `ToolDefinition`: `permission`, `tier`, `required_scopes`, and `side_effects`.
3. Add/update the tool contract in `TOOL_CONTRACTS`.
4. Ensure the tool description explains the operational intent.
5. Ensure inputs/returns include actual field names used by code paths.
6. Ensure chaining guidance reflects realistic sequences (not hypothetical).

## Why This Is Required

The LLM performs better when it sees explicit:

- argument types and required fields
- where required arguments come from
- what the tool returns
- what to call next

This reduces clarification loops and improves autonomous tool chaining.

## Existing Behavior

Tool contracts are automatically injected into each tool description via
`_with_tool_contract()` and exposed in:

- model-facing tool descriptions (tool-calling runtime)
- `/tools` command output in AI chat

So contract metadata is available both at runtime and in operator-visible docs.
