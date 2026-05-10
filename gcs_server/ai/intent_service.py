from __future__ import annotations

import json
import re
import time
from typing import Any

from .prompts import build_intent_prompt
from .schemas import make_empty_intent, validate_intent

_MAX_REPAIR_ATTEMPTS = 1


class IntentService:
    def parse(
        self,
        user_prompt: str,
        *,
        model: Any,
        context_summary: str = "",
        timezone_name: str = "",
    ) -> dict[str, Any]:
        """Parse a rover prompt into a structured intent dict.

        Returns a dict with: intent, parse_errors, provider_name, latency_ms.
        """
        clean_prompt = str(user_prompt or "").strip()
        if not clean_prompt:
            return {
                "intent": make_empty_intent(),
                "parse_errors": ["empty prompt"],
                "provider_name": "",
                "latency_ms": 0,
            }

        system = build_intent_prompt(context_summary)
        start = time.time()

        try:
            from langchain_core.messages import HumanMessage, SystemMessage
        except ImportError as exc:
            raise RuntimeError(
                "LangChain core is not installed. Install gcs_server/requirements-gcs.txt."
            ) from exc

        lc_messages = [SystemMessage(content=system), HumanMessage(content=clean_prompt)]
        intent, errors = _invoke_with_repair(model, lc_messages, repair_attempts=_MAX_REPAIR_ATTEMPTS)
        latency_ms = int((time.time() - start) * 1000)

        provider_name = ""
        try:
            provider_name = str(
                getattr(model, "model_name", None) or getattr(model, "model", None) or ""
            )
        except Exception:
            pass

        return {
            "intent": intent,
            "parse_errors": errors,
            "provider_name": provider_name,
            "latency_ms": latency_ms,
        }


def _invoke_with_repair(
    model: Any,
    messages: list[Any],
    repair_attempts: int = 1,
) -> tuple[dict[str, Any], list[str]]:
    try:
        from langchain_core.messages import AIMessage, HumanMessage
    except ImportError:
        return make_empty_intent(), ["langchain_core not installed"]

    raw_response = model.invoke(messages)
    raw_text = str(getattr(raw_response, "content", raw_response) or "")
    intent, errors = _parse_intent_json(raw_text)
    if not errors:
        return intent, []

    for _ in range(repair_attempts):
        repair_messages = [
            *messages,
            AIMessage(content=raw_text),
            HumanMessage(
                content=(
                    "Your previous response was not valid JSON or did not match the schema. "
                    f"Errors: {'; '.join(errors)}. "
                    "Return ONLY the corrected JSON object with no extra text."
                )
            ),
        ]
        raw_response = model.invoke(repair_messages)
        raw_text = str(getattr(raw_response, "content", raw_response) or "")
        intent, errors = _parse_intent_json(raw_text)
        if not errors:
            return intent, []

    return intent, errors


def _parse_intent_json(text: str) -> tuple[dict[str, Any], list[str]]:
    """Extract and validate the first JSON object from model output."""
    clean = text.strip()
    clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.MULTILINE)
    clean = re.sub(r"\s*```$", "", clean, flags=re.MULTILINE)
    clean = clean.strip()

    match = re.search(r"\{.*\}", clean, re.DOTALL)
    if not match:
        return make_empty_intent(), ["model output contained no JSON object"]

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return make_empty_intent(), [f"JSON parse error: {exc}"]

    if not isinstance(data, dict):
        return make_empty_intent(), ["parsed JSON is not an object"]

    errors = validate_intent(data)
    return _coerce_intent(data), errors


def _coerce_intent(data: dict[str, Any]) -> dict[str, Any]:
    """Coerce a parsed dict into a complete RoverIntent-shaped dict."""
    base = make_empty_intent()
    for key in list(base.keys()):
        if key == "target":
            if isinstance(data.get("target"), dict):
                for k in list(base["target"].keys()):
                    if k in data["target"]:
                        base["target"][k] = data["target"][k]
        elif key == "area":
            if isinstance(data.get("area"), dict):
                for k in list(base["area"].keys()):
                    if k in data["area"]:
                        base["area"][k] = data["area"][k]
        elif key in data:
            base[key] = data[key]
    return base
