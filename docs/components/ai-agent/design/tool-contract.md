# Tool Contract Standard (AI Agent Tools)

Mandatory for any new or modified agent tool.

Related docs:

- [AI Agent Token Efficiency](./token-efficiency.md)

## Required Contract Fields

Every tool must define a contract entry in `TOOL_CONTRACTS` with:

- `inputs`: argument name -> type string
- `required_inputs`: required argument names
- `upstream_from_tools`: which tool outputs can supply required args
- `returns`: returned field -> type string
- `next_tools`: recommended downstream tools for chaining

## Required Implementation Rules

When adding a tool:

1. Register a `ToolDefinition(...)` entry in the tool registry.
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

## Exposure

Contract metadata is injected into each tool description and surfaced in:

- model-facing tool descriptions (tool-calling runtime)
- `/tools` command output in AI chat

So the contract is available both at runtime and in operator-visible docs.

## Runtime Projection Rule

The full contract is the **source of truth**, but the model-facing projection of
that contract does **not** need to serialize every field verbatim on every turn.

Keep the distinction explicit:

- **Right:** keep complete contract metadata for bound dispatcher tools.
- **Wrong:** pay to emit the full contract verbosity into every model-facing tool
  description when the same meaning already exists in the base description,
  inferred argument schema, manifest, or operator-facing capability docs.

Required policy:

- `TOOL_CONTRACTS` stays complete for every bound tool.
- The runtime description may use a **compact projection** of that contract.
- Operator/debug surfaces may still expose the **full contract**.
- Any projection change must be measured with the tool-surface harness and
  checked against agent/HITL prompts because it changes the model-visible tool
  surface.

Preferred model-facing projection order:

1. base description with trigger condition and boundary
2. required arguments and operation/mode/action enum values
3. compact return-shape summary
4. only the minimum follow-up guidance the model actually needs

Fields with the weakest always-on token ROI are usually:

- verbose per-argument `inputs` prose when the schema already carries the types
- detailed `returns` maps for every dispatcher branch
- `upstream_from_tools`
- `next_tools`

Those fields are still valuable in the contract itself and in operator-facing
docs. The optimization target is the **runtime projection**, not the contract
record.
