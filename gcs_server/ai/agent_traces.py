from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AgentTraceStore:
    """Append-only JSONL trace writer for agent runs."""

    def __init__(self, root_dir: str | Path):
        self._root_dir = Path(root_dir)

    def append(self, trace_id: str, event: dict[str, Any]) -> Path:
        clean_trace_id = _clean_trace_id(trace_id)
        now = datetime.now(timezone.utc)
        trace_dir = self._root_dir / now.strftime("%Y-%m-%d")
        trace_dir.mkdir(parents=True, exist_ok=True)
        trace_path = trace_dir / f"{clean_trace_id}.jsonl"

        payload = dict(event)
        payload.setdefault("ts", time.time())
        payload.setdefault("trace_id", clean_trace_id)
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":"), sort_keys=True))
            handle.write("\n")
        return trace_path


def _clean_trace_id(trace_id: str) -> str:
    cleaned = "".join(ch for ch in str(trace_id or "").strip() if ch.isalnum() or ch in ("-", "_"))
    if not cleaned:
        raise ValueError("trace_id is required")
    return cleaned
