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

    def get(self, trace_id: str) -> dict[str, Any]:
        trace_path = self._require_trace_path(trace_id)
        events = self._load_events(trace_path)
        return {
            "trace_id": trace_path.stem,
            "summary": summarize_trace_events(events),
            "events": events,
            "path": str(trace_path),
        }

    def list(self, *, limit: int = 50, day: str = "") -> list[dict[str, Any]]:
        traces: list[dict[str, Any]] = []
        for trace_path in self._iter_trace_paths(day):
            if len(traces) >= max(1, int(limit)):
                break
            events = self._load_events(trace_path)
            traces.append({
                "trace_id": trace_path.stem,
                "summary": summarize_trace_events(events),
                "path": str(trace_path),
            })
        return traces

    def _iter_trace_paths(self, day: str) -> list[Path]:
        clean_day = str(day or "").strip()
        if clean_day:
            candidate = self._root_dir / clean_day
            if not candidate.is_dir():
                return []
            paths = list(candidate.glob("*.jsonl"))
        else:
            paths = list(self._root_dir.glob("*/*.jsonl"))
        return sorted(paths, key=lambda path: path.stat().st_mtime, reverse=True)

    def _require_trace_path(self, trace_id: str) -> Path:
        clean_trace_id = _clean_trace_id(trace_id)
        matches = sorted(
            self._root_dir.glob(f"*/{clean_trace_id}.jsonl"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not matches:
            raise FileNotFoundError(clean_trace_id)
        return matches[0]

    def _load_events(self, trace_path: Path) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        with trace_path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL trace at {trace_path}:{line_number}") from exc
                if isinstance(payload, dict):
                    events.append(payload)
        return events


def summarize_trace_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    if not events:
        return {
            "event_count": 0,
            "started_at": None,
            "ended_at": None,
            "run_mode": "",
            "stop_reason": "",
            "iterations": 0,
            "tool_call_count": 0,
            "tool_failure_count": 0,
            "repeated_tool_failure_count": 0,
        }

    run_start = _first_event_by_type(events, "agent_run_start")
    run_end = _last_event_by_type(events, "agent_run_end")
    return {
        "event_count": len(events),
        "started_at": events[0].get("ts"),
        "ended_at": events[-1].get("ts"),
        "run_mode": str((run_start or {}).get("run_mode") or ""),
        "stop_reason": str((run_end or {}).get("stop_reason") or ""),
        "iterations": int((run_end or {}).get("iterations") or 0),
        "tool_call_count": sum(1 for event in events if event.get("type") == "agent_tool_result"),
        "tool_failure_count": sum(1 for event in events if _event_tool_failed(event)),
        "repeated_tool_failure_count": sum(1 for event in events if event.get("type") == "agent_repeated_tool_failure"),
    }


def _first_event_by_type(events: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    for event in events:
        if event.get("type") == event_type:
            return event
    return None


def _last_event_by_type(events: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("type") == event_type:
            return event
    return None


def _event_tool_failed(event: dict[str, Any]) -> bool:
    if event.get("type") != "agent_tool_result":
        return False
    tool_call = event.get("tool_call")
    if not isinstance(tool_call, dict):
        return False
    result = tool_call.get("result")
    return isinstance(result, dict) and (result.get("ok") is False or bool(result.get("error")))


def _clean_trace_id(trace_id: str) -> str:
    cleaned = "".join(ch for ch in str(trace_id or "").strip() if ch.isalnum() or ch in ("-", "_"))
    if not cleaned:
        raise ValueError("trace_id is required")
    return cleaned
