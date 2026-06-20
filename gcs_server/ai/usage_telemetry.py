"""Provider usage-metadata normalization (P6 cache-hit telemetry).

Prompt caching is already enabled for the agent prefix (``agent_loop.py`` sets
Anthropic ``cache_control``; OpenAI auto-caches). The remaining gap was
*observability*: providers report cache counters, but LangChain nests them in
``usage_metadata.input_token_details`` where nothing surfaced or stored them.

This module promotes those counters to stable top-level keys so cache hits are
visible in every stored message meta and streamed payload, regardless of
provider nesting. It is read-only — it never changes what the model receives.
"""

from __future__ import annotations

from typing import Any

# Stable, provider-neutral keys we promote onto usage_metadata.
CACHE_READ_KEY = "cache_read_input_tokens"
CACHE_CREATION_KEY = "cache_creation_input_tokens"


def normalize_usage_metadata(response: Any) -> dict[str, Any]:
    """Return the response's ``usage_metadata`` with cache counters promoted.

    Reads cache counters from either LangChain's nested
    ``input_token_details.{cache_read,cache_creation}`` or already-flat
    ``cache_{read,creation}_input_tokens`` keys, and copies whichever are
    present to the top level. Leaves the original fields intact. Returns ``{}``
    when no usage metadata is available.
    """
    usage = getattr(response, "usage_metadata", {}) or {}
    if not isinstance(usage, dict):
        return {}
    normalized = dict(usage)

    details = usage.get("input_token_details")
    details = details if isinstance(details, dict) else {}

    cache_read = _first_int(usage.get(CACHE_READ_KEY), details.get("cache_read"))
    cache_creation = _first_int(
        usage.get(CACHE_CREATION_KEY), details.get("cache_creation")
    )
    if cache_read is not None:
        normalized[CACHE_READ_KEY] = cache_read
    if cache_creation is not None:
        normalized[CACHE_CREATION_KEY] = cache_creation
    return normalized


def _first_int(*candidates: Any) -> int | None:
    """First candidate coercible to int, else None (treats bool as absent)."""
    for value in candidates:
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
    return None
