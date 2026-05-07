from __future__ import annotations

import json
import time
from typing import Any, Callable, Iterator

from .provider_registry import resolve_provider
from .session_store import AISessionStore


SYSTEM_PROMPT = """You are the AI chat assistant inside Remote Rover GCS.
Answer operator questions clearly and concisely.
Do not claim to control the rover, publish commands, or start missions.
If the operator asks for rover movement or mission execution, explain that this chat mode is read-only."""


class AIChatService:
    def __init__(self, store: AISessionStore, secret_resolver: Callable[[str], str] | None = None):
        self._store = store
        self._secret_resolver = secret_resolver

    def send_message(self, config: Any, session_id: str, content: str) -> dict[str, Any]:
        clean_content = content.strip()
        if not clean_content:
            raise ValueError("message content is required")

        session = self._store.get_session(session_id, include_messages=False)
        if session is None or session.get("archived_at") is not None:
            raise KeyError("AI session not found")

        provider_id_override = str(session.get("provider_id") or "")
        resolved = resolve_provider(
            config,
            purpose="general_chat",
            provider_id=provider_id_override,
            secret_resolver=self._secret_resolver,
        )
        provider = resolved.provider
        provider_id = str(provider.get("id", ""))
        model_id = str(provider.get("model_id", ""))

        user_message = self._store.add_message(
            session_id,
            role="user",
            content=clean_content,
            provider_id=provider_id,
            model_id=model_id,
        )
        self._store.maybe_auto_title(session_id, clean_content)
        messages = self._store.latest_messages(session_id, limit=40)
        assistant_message = self._invoke_and_store(
            resolved.model,
            session_id=session_id,
            provider_id=provider_id,
            model_id=model_id,
            messages=messages,
        )
        return {
            "user_message": user_message,
            "assistant_message": assistant_message,
            "session": self._store.get_session(session_id, include_messages=False),
        }

    def retry_last_response(self, config: Any, session_id: str) -> dict[str, Any]:
        session = self._store.get_session(session_id, include_messages=False)
        if session is None or session.get("archived_at") is not None:
            raise KeyError("AI session not found")

        messages = self._store.latest_messages(session_id, limit=40)
        if not messages:
            raise ValueError("No message is available to retry.")
        if messages[-1]["role"] == "assistant":
            self._store.delete_message(messages[-1]["id"])
            messages = messages[:-1]
        if not messages or messages[-1]["role"] != "user":
            raise ValueError("Retry requires the latest remaining message to be from the user.")

        resolved = resolve_provider(
            config,
            purpose="general_chat",
            provider_id=str(session.get("provider_id") or ""),
            secret_resolver=self._secret_resolver,
        )
        provider = resolved.provider
        assistant_message = self._invoke_and_store(
            resolved.model,
            session_id=session_id,
            provider_id=str(provider.get("id", "")),
            model_id=str(provider.get("model_id", "")),
            messages=messages,
        )
        return {
            "assistant_message": assistant_message,
            "session": self._store.get_session(session_id, include_messages=False),
        }

    def stream_message_events(self, config: Any, session_id: str, content: str) -> Iterator[str]:
        clean_content = content.strip()
        if not clean_content:
            raise ValueError("message content is required")

        session = self._store.get_session(session_id, include_messages=False)
        if session is None or session.get("archived_at") is not None:
            raise KeyError("AI session not found")

        provider_id_override = str(session.get("provider_id") or "")
        resolved = resolve_provider(
            config,
            purpose="general_chat",
            provider_id=provider_id_override,
            secret_resolver=self._secret_resolver,
        )
        provider = resolved.provider
        provider_id = str(provider.get("id", ""))
        model_id = str(provider.get("model_id", ""))

        user_message = self._store.add_message(
            session_id,
            role="user",
            content=clean_content,
            provider_id=provider_id,
            model_id=model_id,
        )
        self._store.maybe_auto_title(session_id, clean_content)
        yield _json_line({"type": "user_message", "message": user_message})

        messages = self._store.latest_messages(session_id, limit=40)
        langchain_messages = _to_langchain_messages(messages)
        started = time.perf_counter()
        parts: list[str] = []
        interrupted = False
        try:
            model = resolved.model
            stream = getattr(model, "stream", None)
            if callable(stream):
                for chunk in stream(langchain_messages):
                    delta = _response_content(chunk)
                    if not delta:
                        continue
                    parts.append(delta)
                    yield _json_line({"type": "assistant_delta", "delta": delta})
            else:
                response = model.invoke(langchain_messages)
                delta = _response_content(response)
                if delta:
                    parts.append(delta)
                    yield _json_line({"type": "assistant_delta", "delta": delta})
        except GeneratorExit:
            interrupted = True
            raise
        finally:
            content_out = "".join(parts).strip()
            if content_out:
                latency_ms = int((time.perf_counter() - started) * 1000)
                assistant_message = self._store.add_message(
                    session_id,
                    role="assistant",
                    content=content_out,
                    provider_id=provider_id,
                    model_id=model_id,
                    latency_ms=latency_ms,
                    meta={"interrupted": interrupted},
                )
                if not interrupted:
                    yield _json_line({"type": "assistant_message", "message": assistant_message})

    def _invoke_and_store(
        self,
        model: Any,
        *,
        session_id: str,
        provider_id: str,
        model_id: str,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        langchain_messages = _to_langchain_messages(messages)
        started = time.perf_counter()
        response = model.invoke(langchain_messages)
        latency_ms = int((time.perf_counter() - started) * 1000)
        content = _response_content(response)
        return self._store.add_message(
            session_id,
            role="assistant",
            content=content,
            provider_id=provider_id,
            model_id=model_id,
            latency_ms=latency_ms,
            meta={"response_metadata": getattr(response, "response_metadata", {}) or {}},
        )


def _to_langchain_messages(messages: list[dict[str, Any]]) -> list[Any]:
    try:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    except ImportError as exc:
        raise RuntimeError("LangChain core is not installed. Install gcs_server/requirements-gcs.txt.") from exc

    out: list[Any] = [SystemMessage(content=SYSTEM_PROMPT)]
    for message in messages:
        role = message.get("role")
        content = str(message.get("content") or "")
        if role == "user":
            out.append(HumanMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
    return out


def _response_content(response: Any) -> str:
    content = getattr(response, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return str(content or "").strip()


def _json_line(data: dict[str, Any]) -> str:
    return f"{json.dumps(data, separators=(',', ':'))}\n"
