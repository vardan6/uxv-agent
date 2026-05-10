from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo


ORDINAL_WORDS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
}

MONTH_PATTERN = r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
DATE_BETWEEN_RE = re.compile(
    rf"\b(?:between|from)\s+((?:\d{{4}}-\d{{2}}-\d{{2}})|(?:{MONTH_PATTERN}\s+\d{{1,2}}(?:,\s*\d{{4}})?))\s+(?:and|to)\s+((?:\d{{4}}-\d{{2}}-\d{{2}})|(?:{MONTH_PATTERN}\s+\d{{1,2}}(?:,\s*\d{{4}})?))",
    re.IGNORECASE,
)
DATE_ON_RE = re.compile(
    rf"\b(?:on|for|from)\s+((?:\d{{4}}-\d{{2}}-\d{{2}})|(?:{MONTH_PATTERN}\s+\d{{1,2}}(?:,\s*\d{{4}})?))\b",
    re.IGNORECASE,
)
LAST_N_RE = re.compile(r"\b(?:last|latest|most recent)\s+(\d+)\s+sessions?\b", re.IGNORECASE)
FROM_LAST_RE = re.compile(r"\b((?:\d+)(?:st|nd|rd|th)?|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+from\s+last\b", re.IGNORECASE)
ORDINAL_SESSION_RE = re.compile(r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d+(?:st|nd|rd|th)?)\s+sessions?\b", re.IGNORECASE)
SESSION_ID_RE = re.compile(r"\bsession-[a-z0-9]+\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ReplaySessionSelection:
    selector_type: str
    resolved_session_ids: list[str]
    resolution_basis: dict[str, Any]
    ambiguous: bool
    needs_clarification: bool
    matched_count: int
    preview_sessions: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "selector_type": self.selector_type,
            "resolved_session_ids": self.resolved_session_ids,
            "resolution_basis": self.resolution_basis,
            "ambiguous": self.ambiguous,
            "needs_clarification": self.needs_clarification,
            "matched_count": self.matched_count,
            "preview_sessions": self.preview_sessions,
        }


class ReplaySessionResolver:
    def __init__(self, list_sessions_func):
        self._list_sessions = list_sessions_func

    def resolve(
        self,
        selector: str | dict[str, Any] | None = None,
        *,
        timezone_name: str = "",
        active_session_id: str | None = None,
        limit: int = 1000,
    ) -> ReplaySessionSelection:
        tz_name, tzinfo = _resolve_timezone(timezone_name)
        sessions_desc = self._list_sessions(limit=limit, order="desc")
        sessions_asc = list(reversed(sessions_desc))
        clean_selector = selector if isinstance(selector, dict) else str(selector or "").strip()

        if isinstance(clean_selector, dict):
            return self._resolve_structured(clean_selector, tz_name, tzinfo, active_session_id, sessions_desc, sessions_asc)
        if not clean_selector:
            if active_session_id:
                return _selection(
                    "active_session",
                    [active_session_id],
                    {"timezone": tz_name, "sort_order": "started_at_desc", "source": "active_session"},
                    sessions_desc,
                )
            return _selection(
                "default_recent",
                [item["session_id"] for item in sessions_desc[:1]],
                {"timezone": tz_name, "sort_order": "started_at_desc", "source": "default_recent"},
                sessions_desc,
            )

        text = clean_selector
        lower = text.lower()

        explicit_ids = list(dict.fromkeys(match.lower() for match in SESSION_ID_RE.findall(text)))
        if explicit_ids:
            return _selection(
                "explicit_id",
                explicit_ids,
                {"timezone": tz_name, "sort_order": "explicit", "source": "prompt"},
                sessions_desc,
            )

        range_match = DATE_BETWEEN_RE.search(text)
        if range_match:
            start_date = _parse_date_text(range_match.group(1), tzinfo)
            end_date = _parse_date_text(range_match.group(2), tzinfo)
            if start_date and end_date:
                if end_date < start_date:
                    start_date, end_date = end_date, start_date
                return self._resolve_date_range(start_date, end_date, tz_name, tzinfo, sessions_desc)

        if "yesterday" in lower:
            target = datetime.now(tzinfo).date() - timedelta(days=1)
            return self._resolve_date_range(target, target, tz_name, tzinfo, sessions_desc, selector_type="relative_day")
        if "today" in lower:
            target = datetime.now(tzinfo).date()
            return self._resolve_date_range(target, target, tz_name, tzinfo, sessions_desc, selector_type="relative_day")

        on_match = DATE_ON_RE.search(text)
        if on_match:
            target = _parse_date_text(on_match.group(1), tzinfo)
            if target:
                return self._resolve_date_range(target, target, tz_name, tzinfo, sessions_desc)

        if "all sessions" in lower or "every session" in lower:
            return _selection(
                "all_sessions",
                [item["session_id"] for item in sessions_desc],
                {"timezone": tz_name, "sort_order": "started_at_desc", "source": "all_sessions"},
                sessions_desc,
            )

        last_n_match = LAST_N_RE.search(lower)
        if last_n_match:
            count = max(1, int(last_n_match.group(1)))
            return _selection(
                "relative_slice",
                [item["session_id"] for item in sessions_desc[:count]],
                {"timezone": tz_name, "sort_order": "started_at_desc", "count": count, "source": "last_n"},
                sessions_desc,
            )

        if "last but not the last one" in lower or "before last" in lower or "one before last" in lower or "previous session" in lower:
            return _selection(
                "relative_order",
                [item["session_id"] for item in sessions_desc[1:2]],
                {"timezone": tz_name, "sort_order": "started_at_desc", "ordinal": 2, "source": "previous_session"},
                sessions_desc,
            )

        from_last_match = FROM_LAST_RE.search(lower)
        if from_last_match:
            ordinal = _ordinal_value(from_last_match.group(1))
            return _selection(
                "relative_order",
                [item["session_id"] for item in sessions_desc[max(0, ordinal - 1):ordinal]],
                {"timezone": tz_name, "sort_order": "started_at_desc", "ordinal": ordinal, "source": "from_last"},
                sessions_desc,
            )

        if "last session" in lower or "latest session" in lower or "most recent session" in lower:
            return _selection(
                "relative_order",
                [item["session_id"] for item in sessions_desc[:1]],
                {"timezone": tz_name, "sort_order": "started_at_desc", "ordinal": 1, "source": "last_session"},
                sessions_desc,
            )

        if "first session" in lower:
            return _selection(
                "absolute_order",
                [item["session_id"] for item in sessions_asc[:1]],
                {"timezone": tz_name, "sort_order": "started_at_asc", "ordinal": 1, "source": "first_session"},
                sessions_asc,
            )

        ordinal_match = ORDINAL_SESSION_RE.search(lower)
        if ordinal_match:
            ordinal = _ordinal_value(ordinal_match.group(1))
            return _selection(
                "absolute_order",
                [item["session_id"] for item in sessions_asc[max(0, ordinal - 1):ordinal]],
                {"timezone": tz_name, "sort_order": "started_at_asc", "ordinal": ordinal, "source": "ordinal_session"},
                sessions_asc,
            )

        if active_session_id:
            return _selection(
                "active_session",
                [active_session_id],
                {"timezone": tz_name, "sort_order": "started_at_desc", "source": "active_session_fallback"},
                sessions_desc,
            )
        return _selection(
            "default_recent",
            [item["session_id"] for item in sessions_desc[:1]],
            {"timezone": tz_name, "sort_order": "started_at_desc", "source": "default_recent_fallback"},
            sessions_desc,
        )

    def _resolve_structured(
        self,
        selector: dict[str, Any],
        timezone_name: str,
        tzinfo,
        active_session_id: str | None,
        sessions_desc: list[dict[str, Any]],
        sessions_asc: list[dict[str, Any]],
    ) -> ReplaySessionSelection:
        kind = str(selector.get("kind") or "").strip().lower()
        if kind == "explicit_ids":
            session_ids = [str(item).strip() for item in selector.get("session_ids", []) if str(item).strip()]
            return _selection(kind, session_ids, {"timezone": timezone_name, "sort_order": "explicit"}, sessions_desc)
        if kind == "relative_order":
            direction = str(selector.get("direction") or "last").strip().lower()
            ordinal = max(1, int(selector.get("ordinal", 1)))
            ordered = sessions_desc if direction == "last" else sessions_asc
            sort_order = "started_at_desc" if direction == "last" else "started_at_asc"
            return _selection(
                kind,
                [item["session_id"] for item in ordered[max(0, ordinal - 1):ordinal]],
                {"timezone": timezone_name, "sort_order": sort_order, "ordinal": ordinal, "direction": direction},
                ordered,
            )
        if kind == "relative_slice":
            direction = str(selector.get("direction") or "last").strip().lower()
            count = max(1, int(selector.get("count", 1)))
            ordered = sessions_desc if direction == "last" else sessions_asc
            sort_order = "started_at_desc" if direction == "last" else "started_at_asc"
            return _selection(
                kind,
                [item["session_id"] for item in ordered[:count]],
                {"timezone": timezone_name, "sort_order": sort_order, "count": count, "direction": direction},
                ordered,
            )
        if kind == "date_range":
            start_date = _parse_date_text(str(selector.get("date_from") or ""), tzinfo)
            end_date = _parse_date_text(str(selector.get("date_to") or ""), tzinfo)
            if start_date and end_date:
                if end_date < start_date:
                    start_date, end_date = end_date, start_date
                return self._resolve_date_range(start_date, end_date, timezone_name, tzinfo, sessions_desc)
        if kind == "relative_day":
            days_ago = max(0, int(selector.get("days_ago", 0)))
            target = datetime.now(tzinfo).date() - timedelta(days=days_ago)
            return self._resolve_date_range(target, target, timezone_name, tzinfo, sessions_desc, selector_type="relative_day")
        if kind == "all_sessions":
            return _selection(
                kind,
                [item["session_id"] for item in sessions_desc],
                {"timezone": timezone_name, "sort_order": "started_at_desc"},
                sessions_desc,
            )
        if active_session_id:
            return _selection(
                "active_session",
                [active_session_id],
                {"timezone": timezone_name, "sort_order": "started_at_desc", "source": "structured_fallback"},
                sessions_desc,
            )
        return _selection(
            "default_recent",
            [item["session_id"] for item in sessions_desc[:1]],
            {"timezone": timezone_name, "sort_order": "started_at_desc", "source": "structured_default_recent"},
            sessions_desc,
        )

    def _resolve_date_range(
        self,
        start_date: date,
        end_date: date,
        timezone_name: str,
        tzinfo,
        sessions_desc: list[dict[str, Any]],
        *,
        selector_type: str = "date_range",
    ) -> ReplaySessionSelection:
        start_ts = datetime.combine(start_date, time.min, tzinfo=tzinfo).timestamp()
        end_ts = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=tzinfo).timestamp()
        matched = [
            item["session_id"]
            for item in sessions_desc
            if start_ts <= float(item.get("started_at") or 0.0) < end_ts
        ]
        return _selection(
            selector_type,
            matched,
            {
                "timezone": timezone_name,
                "sort_order": "started_at_desc",
                "date_from": start_date.isoformat(),
                "date_to": end_date.isoformat(),
            },
            sessions_desc,
        )


def _selection(selector_type: str, session_ids: list[str], resolution_basis: dict[str, Any], sessions: list[dict[str, Any]]) -> ReplaySessionSelection:
    unique_ids = list(dict.fromkeys(session_ids))
    preview = [item for item in sessions if item.get("session_id") in set(unique_ids)]
    return ReplaySessionSelection(
        selector_type=selector_type,
        resolved_session_ids=unique_ids,
        resolution_basis=resolution_basis,
        ambiguous=False,
        needs_clarification=False,
        matched_count=len(unique_ids),
        preview_sessions=preview[:10],
    )


def _resolve_timezone(timezone_name: str) -> tuple[str, Any]:
    clean = str(timezone_name or "").strip()
    if clean:
        try:
            return clean, ZoneInfo(clean)
        except Exception:
            pass
    local = datetime.now().astimezone().tzinfo
    tz_name = getattr(local, "key", None) or str(local or "UTC")
    return tz_name, local


def _ordinal_value(raw: str) -> int:
    clean = str(raw or "").strip().lower()
    if clean in ORDINAL_WORDS:
        return ORDINAL_WORDS[clean]
    clean = re.sub(r"(st|nd|rd|th)$", "", clean)
    try:
        return max(1, int(clean))
    except ValueError:
        return 1


def _parse_date_text(text: str, tzinfo) -> date | None:
    clean = " ".join(str(text or "").replace(",", " ").split())
    if not clean:
        return None
    try:
        return datetime.strptime(clean, "%Y-%m-%d").date()
    except ValueError:
        pass

    parts = clean.split()
    if len(parts) not in {2, 3}:
        return None
    month_token = parts[0].lower()
    month = _month_from_token(month_token)
    if month is None:
        return None
    try:
        day = int(parts[1])
    except ValueError:
        return None
    year = datetime.now(tzinfo).year
    if len(parts) == 3:
        try:
            year = int(parts[2])
        except ValueError:
            return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _month_from_token(token: str) -> int | None:
    clean = token[:3].lower()
    months = {name[:3].lower(): index for index, name in enumerate(calendar.month_name) if name}
    return months.get(clean)
