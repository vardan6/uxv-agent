from __future__ import annotations

from ai.usage_telemetry import (
    CACHE_CREATION_KEY,
    CACHE_READ_KEY,
    normalize_usage_metadata,
)


class _Response:
    def __init__(self, usage_metadata):
        self.usage_metadata = usage_metadata


def test_promotes_nested_cache_counters_from_langchain_shape():
    # LangChain nests cache counters under input_token_details.
    resp = _Response(
        {
            "input_tokens": 6100,
            "output_tokens": 42,
            "total_tokens": 6142,
            "input_token_details": {"cache_read": 5800, "cache_creation": 300},
        }
    )
    usage = normalize_usage_metadata(resp)
    assert usage[CACHE_READ_KEY] == 5800
    assert usage[CACHE_CREATION_KEY] == 300
    # Original fields stay intact.
    assert usage["input_tokens"] == 6100
    assert usage["input_token_details"] == {"cache_read": 5800, "cache_creation": 300}


def test_accepts_already_flat_cache_counters():
    resp = _Response(
        {
            "input_tokens": 6100,
            CACHE_READ_KEY: 5800,
            CACHE_CREATION_KEY: 0,
        }
    )
    usage = normalize_usage_metadata(resp)
    assert usage[CACHE_READ_KEY] == 5800
    assert usage[CACHE_CREATION_KEY] == 0


def test_no_cache_counters_leaves_keys_absent():
    # No cache fired (or provider does not report them) -> no promoted keys.
    resp = _Response({"input_tokens": 400, "output_tokens": 10})
    usage = normalize_usage_metadata(resp)
    assert CACHE_READ_KEY not in usage
    assert CACHE_CREATION_KEY not in usage
    assert usage["input_tokens"] == 400


def test_missing_or_invalid_usage_metadata_returns_empty_dict():
    assert normalize_usage_metadata(_Response(None)) == {}
    assert normalize_usage_metadata(_Response("not-a-dict")) == {}
    assert normalize_usage_metadata(object()) == {}


def test_bool_and_float_counters_are_coerced_or_skipped():
    # Booleans are not valid counts; integral floats coerce to int.
    resp = _Response(
        {
            "input_token_details": {"cache_read": True, "cache_creation": 256.0},
        }
    )
    usage = normalize_usage_metadata(resp)
    assert CACHE_READ_KEY not in usage  # True skipped
    assert usage[CACHE_CREATION_KEY] == 256
