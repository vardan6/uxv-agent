from __future__ import annotations

import math
import re
from typing import Any

from backend.replay_session_resolver import ReplaySessionResolver
from backend.replay_store import ReplayStore


SESSION_ID_RE = re.compile(r"\bsession-[a-z0-9]+\b", re.IGNORECASE)


class ReplayAnalyticsService:
    def __init__(self, store: ReplayStore):
        self._store = store
        self._resolver = ReplaySessionResolver(self.list_sessions)

    def list_sessions(
        self,
        limit: int = 100,
        *,
        started_at_from: float | None = None,
        started_at_to: float | None = None,
        order: str = "desc",
    ) -> list[dict[str, Any]]:
        return self._store.list_sessions(
            limit=limit,
            started_at_from=started_at_from,
            started_at_to=started_at_to,
            order=order,
        )

    def get_session_summary(self, session_id: str) -> dict[str, Any] | None:
        return self._store.get_session_summary(session_id)

    def get_session_metrics(self, session_id: str, *, refresh: bool = False) -> dict[str, Any] | None:
        session = self._store.get_session(session_id)
        if session is None:
            return None
        if not refresh and session.get("ended_at") is not None:
            cached = self._store.get_cached_session_metrics(session_id)
            if cached is not None:
                return cached
        metrics = self._compute_metrics(session_id, session)
        self._store.save_session_metrics(session_id, metrics)
        return self._store.get_cached_session_metrics(session_id) or metrics

    def get_session_path(self, session_id: str, *, downsample: int = 1, limit: int | None = None) -> dict[str, Any] | None:
        session = self._store.get_session(session_id)
        if session is None:
            return None
        samples = self._store.list_telemetry_samples(session_id, limit=limit)
        step = max(1, int(downsample))
        points: list[dict[str, Any]] = []
        for index, sample in enumerate(samples):
            if index % step != 0:
                continue
            position = sample.get("position")
            gps = sample.get("gps")
            if position is None and gps is None:
                continue
            points.append(
                {
                    "ts": sample["ts"],
                    "position_frame": sample.get("position_frame") or "unknown",
                    "position": position,
                    "gps": gps,
                }
            )
        return {
            "session_id": session_id,
            "point_count": len(points),
            "downsample": step,
            "points": points,
        }

    def search_session_events(
        self,
        session_id: str,
        *,
        event_type: str = "",
        text: str = "",
        limit: int = 100,
    ) -> dict[str, Any] | None:
        if self._store.get_session(session_id) is None:
            return None
        events = self._store.list_session_events(session_id, event_type=event_type, text=text, limit=limit)
        return {
            "session_id": session_id,
            "query": {
                "event_type": event_type.strip() or None,
                "text": text.strip() or None,
                "limit": max(1, int(limit)),
            },
            "count": len(events),
            "events": events,
        }

    def compare_sessions(self, session_ids: list[str]) -> dict[str, Any]:
        comparisons = []
        for session_id in session_ids:
            summary = self.get_session_summary(session_id)
            metrics = self.get_session_metrics(session_id)
            if summary is None or metrics is None:
                continue
            comparisons.append({"session": summary, "metrics": metrics})
        return {"session_ids": session_ids, "comparisons": comparisons}

    def resolve_sessions(
        self,
        selector: str | dict[str, Any] | None,
        *,
        timezone_name: str = "",
        active_session_id: str | None = None,
        limit: int = 1000,
    ) -> dict[str, Any]:
        return self._resolver.resolve(
            selector,
            timezone_name=timezone_name,
            active_session_id=active_session_id,
            limit=limit,
        ).to_dict()

    def aggregate_sessions(
        self,
        *,
        session_ids: list[str] | None = None,
        selector: str | dict[str, Any] | None = None,
        timezone_name: str = "",
        active_session_id: str | None = None,
        limit: int = 1000,
        top_n: int = 5,
    ) -> dict[str, Any]:
        if session_ids:
            clean_ids = [str(item).strip() for item in session_ids if str(item).strip()]
            selection = {
                "selector_type": "explicit_id_list",
                "resolved_session_ids": clean_ids,
                "resolution_basis": {"timezone": timezone_name or "", "source": "session_ids"},
                "ambiguous": False,
                "needs_clarification": False,
                "matched_count": len(clean_ids),
                "preview_sessions": [],
            }
        else:
            selection = self.resolve_sessions(
                selector,
                timezone_name=timezone_name,
                active_session_id=active_session_id,
                limit=limit,
            )
        resolved_ids = list(dict.fromkeys(selection.get("resolved_session_ids") or []))
        rows: list[dict[str, Any]] = []
        for session_id in resolved_ids:
            summary = self.get_session_summary(session_id)
            metrics = self.get_session_metrics(session_id)
            if summary is None or metrics is None:
                continue
            rows.append({"session": summary, "metrics": metrics})
        return {
            "selection": selection,
            "session_ids": [row["session"]["session_id"] for row in rows],
            "session_count": len(rows),
            "summary": _aggregate_summary(rows, top_n=max(1, int(top_n))),
            "sessions": rows,
        }

    def build_ai_replay_context(
        self,
        user_message: str,
        *,
        active_session_id: str | None = None,
        timezone_name: str = "",
    ) -> dict[str, Any]:
        clean = str(user_message or "").strip()
        lower = clean.lower()
        if not _looks_like_replay_question(lower):
            return {"available": False}
        wants_compare = any(token in lower for token in ("compare", "all sessions", "every session", "across sessions"))
        wants_aggregate = wants_compare or any(token in lower for token in ("total", "average", "avg", "overall", "combined", "sum"))
        wants_events = "event" in lower or "error" in lower or "warning" in lower
        wants_path = "path" in lower or "route" in lower or "track" in lower
        wants_metrics = _looks_like_metrics_question(lower)
        wants_summary_only = _looks_like_session_listing(lower) and not (wants_metrics or wants_events or wants_path)
        selection = self.resolve_sessions(
            clean,
            timezone_name=timezone_name,
            active_session_id=active_session_id,
            limit=1000,
        )
        target_ids = list(selection.get("resolved_session_ids") or [])

        sessions: list[dict[str, Any]] = []
        for session_id in target_ids:
            summary = self.get_session_summary(session_id)
            if summary is None:
                continue
            item: dict[str, Any] = {
                "session_id": session_id,
                "summary": summary,
            }
            metrics = None if wants_summary_only else self.get_session_metrics(session_id)
            if not wants_summary_only and metrics is None:
                continue
            if metrics is not None:
                item["metrics"] = metrics
            if wants_events:
                item["events"] = self.search_session_events(session_id, text=_event_search_text(lower), limit=20)
            if wants_path and metrics is not None:
                item["path"] = self.get_session_path(session_id, downsample=_path_downsample(metrics), limit=500)
            sessions.append(item)

        aggregate = None
        if not wants_summary_only and (wants_aggregate or len(sessions) > 1):
            aggregate = self.aggregate_sessions(
                session_ids=[item["session_id"] for item in sessions],
                timezone_name=timezone_name,
            )

        return {
            "available": True,
            "selection": selection,
            "requested_compare": wants_compare,
            "requested_aggregate": wants_aggregate,
            "requested_events": wants_events,
            "requested_path": wants_path,
            "requested_metrics": wants_metrics,
            "aggregate": aggregate,
            "sessions": sessions,
        }

    def _compute_metrics(self, session_id: str, session: dict[str, Any]) -> dict[str, Any]:
        samples = self._store.list_telemetry_samples(session_id)
        if not samples:
            return {
                "session_id": session_id,
                "computed_at": None,
                "duration_s": _session_duration_fallback(session),
                "duration_source": "session_bounds",
                "telemetry_sample_count": 0,
                "position_sample_count": 0,
                "path_length_m": 0.0,
                "net_displacement_m": 0.0,
                "max_distance_from_start_m": 0.0,
                "max_speed_m_s": 0.0,
                "max_speed_km_h": 0.0,
                "position_frame": "unknown",
                "origin_source": None,
                "origin_sample_ts": None,
                "coverage": {
                    "telemetry_samples_total": 0,
                    "telemetry_samples_used": 0,
                    "position_coverage_ratio": 0.0,
                },
            }

        first_ts = min(sample["ts"] for sample in samples)
        last_ts = max(sample["ts"] for sample in samples)
        position_samples = [sample for sample in samples if sample.get("position") is not None]
        path_length = 0.0
        max_distance = 0.0
        displacement = 0.0
        origin = position_samples[0]["position"] if position_samples else None
        origin_ts = position_samples[0]["ts"] if position_samples else None
        max_distance_ts = origin_ts
        if len(position_samples) >= 2:
            for prev, curr in zip(position_samples, position_samples[1:]):
                path_length += _distance(prev["position"], curr["position"])
            displacement = _distance(position_samples[0]["position"], position_samples[-1]["position"])
        if origin is not None:
            for sample in position_samples:
                distance = _distance(origin, sample["position"])
                if distance >= max_distance:
                    max_distance = distance
                    max_distance_ts = sample["ts"]
        max_speed_m_s = max((float(sample["speed_m_s"]) for sample in samples if sample.get("speed_m_s") is not None), default=0.0)
        max_speed_km_h = max((float(sample["speed_km_h"]) for sample in samples if sample.get("speed_km_h") is not None), default=0.0)
        return {
            "session_id": session_id,
            "computed_at": None,
            "duration_s": round(max(0.0, last_ts - first_ts), 3),
            "duration_source": "telemetry_bounds",
            "telemetry_sample_count": len(samples),
            "position_sample_count": len(position_samples),
            "path_length_m": round(path_length, 3),
            "net_displacement_m": round(displacement, 3),
            "max_distance_from_start_m": round(max_distance, 3),
            "max_distance_sample_ts": max_distance_ts,
            "max_speed_m_s": round(max_speed_m_s, 3),
            "max_speed_km_h": round(max_speed_km_h, 3),
            "position_frame": _dominant_position_frame(position_samples),
            "origin_source": "first_valid_position_sample" if origin is not None else None,
            "origin_sample_ts": origin_ts,
            "coverage": {
                "telemetry_samples_total": len(samples),
                "telemetry_samples_used": len(position_samples),
                "position_coverage_ratio": round(len(position_samples) / len(samples), 4),
            },
        }


def _looks_like_replay_question(text: str) -> bool:
    direct_keywords = (
        "replay",
        "telemetry",
        "runtime event",
        "path length",
        "distance from",
        "duration",
        "route",
        "track",
        "compare sessions",
    )
    if any(keyword in text for keyword in direct_keywords):
        return True
    return "session" in text and any(
        token in text
        for token in ("path", "distance", "duration", "event", "compare", "telemetry", "runtime", "replay")
    )


def _distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    dx = float(b["x"]) - float(a["x"])
    dy = float(b["y"]) - float(a["y"])
    dz = float(b.get("z", 0.0)) - float(a.get("z", 0.0))
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _dominant_position_frame(samples: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for sample in samples:
        frame = str(sample.get("position_frame") or "unknown")
        counts[frame] = counts.get(frame, 0) + 1
    if not counts:
        return "unknown"
    return max(counts.items(), key=lambda item: item[1])[0]


def _session_duration_fallback(session: dict[str, Any]) -> float:
    started_at = float(session.get("started_at") or 0.0)
    ended_at = float(session.get("ended_at") or started_at)
    return round(max(0.0, ended_at - started_at), 3)


def _path_downsample(metrics: dict[str, Any]) -> int:
    sample_count = int(metrics.get("position_sample_count") or 0)
    if sample_count <= 200:
        return 1
    return max(1, math.ceil(sample_count / 200))


def _event_search_text(text: str) -> str:
    for token in ("error", "warning", "warn", "disconnect", "connect", "session"):
        if token in text:
            return token
    return ""


def _looks_like_session_listing(text: str) -> bool:
    return any(token in text for token in ("list", "show", "enumerate", "which sessions", "what sessions"))


def _looks_like_metrics_question(text: str) -> bool:
    return any(
        token in text
        for token in (
            "duration",
            "longest",
            "shortest",
            "travel distance",
            "path length",
            "distance",
            "furthest",
            "farthest",
            "max distance",
            "speed",
            "metrics",
            "compare",
            "top ",
        )
    )


def _aggregate_summary(rows: list[dict[str, Any]], top_n: int = 5) -> dict[str, Any]:
    if not rows:
        return {
            "session_count": 0,
            "total_duration_s": 0.0,
            "total_path_length_m": 0.0,
            "average_duration_s": 0.0,
            "average_path_length_m": 0.0,
            "longest_session_id": None,
            "latest_session_id": None,
            "first_session_id": None,
            "furthest_session_from_start_id": None,
            "top_sessions_by_duration": [],
            "top_sessions_by_travel_distance": [],
            "top_sessions_by_path_length": [],
            "top_sessions_by_max_distance_from_start": [],
        }
    total_duration = sum(float(row["metrics"].get("duration_s") or 0.0) for row in rows)
    total_path = sum(float(row["metrics"].get("path_length_m") or 0.0) for row in rows)
    longest = max(rows, key=lambda row: float(row["metrics"].get("duration_s") or 0.0))
    furthest = max(rows, key=lambda row: float(row["metrics"].get("max_distance_from_start_m") or 0.0))
    latest = max(rows, key=lambda row: float(row["session"].get("started_at") or 0.0))
    first = min(rows, key=lambda row: float(row["session"].get("started_at") or 0.0))
    count = max(1, int(top_n))
    return {
        "session_count": len(rows),
        "total_duration_s": round(total_duration, 3),
        "total_path_length_m": round(total_path, 3),
        "average_duration_s": round(total_duration / len(rows), 3),
        "average_path_length_m": round(total_path / len(rows), 3),
        "longest_session_id": longest["session"]["session_id"],
        "latest_session_id": latest["session"]["session_id"],
        "first_session_id": first["session"]["session_id"],
        "furthest_session_from_start_id": furthest["session"]["session_id"],
        "top_sessions_by_duration": _top_ranked_sessions(rows, "duration_s", count),
        "top_sessions_by_travel_distance": _top_ranked_sessions(rows, "path_length_m", count),
        "top_sessions_by_path_length": _top_ranked_sessions(rows, "path_length_m", count),
        "top_sessions_by_max_distance_from_start": _top_ranked_sessions(rows, "max_distance_from_start_m", count),
    }


def _top_ranked_sessions(rows: list[dict[str, Any]], metric_key: str, count: int) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda row: float(row["metrics"].get(metric_key) or 0.0),
        reverse=True,
    )
    top_rows = ordered[:max(1, int(count))]
    return [
        {
            "session_id": row["session"]["session_id"],
            "started_at": row["session"].get("started_at"),
            metric_key: row["metrics"].get(metric_key),
        }
        for row in top_rows
    ]
