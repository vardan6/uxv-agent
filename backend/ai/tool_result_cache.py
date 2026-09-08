"""In-session tool result cache (Tier 2 #6 of token-efficiency plan).

Caches results of read-only tools whose output is stable on the timescale of a
chat session (scene summary, replay history, settings, etc.). Live-state tools
(current rover pose, recent telemetry, sensor freshness) are NOT cached.

Cache keyed by (session_id, tool_name, args_hash); TTL-bounded; in-process.
Only successful results (`ok: true` or no `ok` field present) are cached;
failures fall through to the existing retry-on-same-failure guard in agent_loop.

Kill switch: `AI_TOOL_RESULT_CACHE_DISABLED=1`.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Any

from .tool_registry import cacheable_tool_names, tool_cache_ttl_s


# Tools whose output is stable across calls within a session (O9: derived from
# each tool's ToolMeta.cacheable declaration in tool_registry.py, not a second
# independent list). Excludes: live-state queries (rover pose, telemetry,
# sensor freshness), pose-dependent spatial queries, route planners (depend on
# current pose), and any mutating tool.
CACHEABLE_TOOL_NAMES: frozenset[str] = cacheable_tool_names()

_DEFAULT_TTL_SECONDS = 300


def _enabled() -> bool:
    return os.getenv("AI_TOOL_RESULT_CACHE_DISABLED", "").strip().lower() not in {"1", "true", "yes"}


def _args_hash(tool_args: Any) -> str:
    try:
        payload = json.dumps(tool_args, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        payload = repr(tool_args)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _is_cacheable_result(tool_result: Any) -> bool:
    if not isinstance(tool_result, dict):
        return False
    if tool_result.get("ok") is False:
        return False
    if tool_result.get("error"):
        return False
    return True


class ToolResultCache:
    """Thread-safe in-process cache. One instance per AIChatService."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[float, Any]] = {}
        self._hits = 0
        self._misses = 0
        self._stores = 0
        self._lock = threading.Lock()

    @staticmethod
    def _key(session_id: str, tool_name: str, tool_args: Any) -> str:
        return f"{session_id}\x00{tool_name}\x00{_args_hash(tool_args)}"

    def get(self, session_id: str, tool_name: str, tool_args: Any) -> Any | None:
        if not _enabled() or not session_id or tool_name not in CACHEABLE_TOOL_NAMES:
            return None
        key = self._key(session_id, tool_name, tool_args)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None
            expires_at, value = entry
            if expires_at < time.time():
                self._entries.pop(key, None)
                self._misses += 1
                return None
            self._hits += 1
            return value

    def set(self, session_id: str, tool_name: str, tool_args: Any, tool_result: Any) -> None:
        if not _enabled() or not session_id or tool_name not in CACHEABLE_TOOL_NAMES:
            return
        if not _is_cacheable_result(tool_result):
            return
        ttl = tool_cache_ttl_s(tool_name, default=_DEFAULT_TTL_SECONDS)
        key = self._key(session_id, tool_name, tool_args)
        with self._lock:
            self._entries[key] = (time.time() + ttl, tool_result)
            self._stores += 1

    def invalidate_session(self, session_id: str) -> None:
        if not session_id:
            return
        prefix = f"{session_id}\x00"
        with self._lock:
            for cached_key in [k for k in self._entries if k.startswith(prefix)]:
                self._entries.pop(cached_key, None)

    def invalidate_tool(self, tool_name: str) -> None:
        token = f"\x00{tool_name}\x00"
        with self._lock:
            for cached_key in [k for k in self._entries if token in k]:
                self._entries.pop(cached_key, None)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "stores": self._stores,
                "size": len(self._entries),
            }
