from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable


OPENAI_COMPATIBLE_PROVIDER_TYPES = {
    "openrouter",
    "nvidia_nim",
    "openai",
    "google_gemini",
    "lm_studio",
    "mistral",
    "together",
    "groq",
    "huggingface",
    "openai_compatible",
}


@dataclass(slots=True)
class ResolvedProvider:
    provider: dict[str, Any]
    model: Any


def resolve_provider(
    config: Any,
    *,
    purpose: str = "general_chat",
    provider_id: str = "",
    secret_resolver: Callable[[str], str] | None = None,
) -> ResolvedProvider:
    providers = [provider for provider in config.llm_providers if isinstance(provider, dict)]
    provider = _find_provider(providers, provider_id) if provider_id else _provider_from_routing(config.model_routing, providers, purpose)
    if provider is None:
        raise ValueError("No LLM provider is configured for General Chat.")
    if not provider.get("enabled", True):
        raise ValueError(f"LLM provider '{provider.get('display_name') or provider.get('id')}' is disabled.")
    return ResolvedProvider(provider=provider, model=build_chat_model(provider, secret_resolver=secret_resolver))


def build_chat_model(provider: dict[str, Any], *, secret_resolver: Callable[[str], str] | None = None) -> Any:
    provider_type = str(provider.get("provider_type", "openai_compatible"))
    if provider_type == "ollama":
        return _build_ollama_chat_model(provider)
    if provider_type in {"anthropic", "cohere"}:
        raise ValueError(f"{provider_type} chat support will be added with the provider-specific LangChain adapter.")
    if provider_type not in OPENAI_COMPATIBLE_PROVIDER_TYPES:
        raise ValueError(f"Unsupported LLM provider type: {provider_type}")

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise RuntimeError("LangChain OpenAI integration is not installed. Install gcs_server/requirements-gcs.txt.") from exc

    api_key = _api_key_for_provider(provider, secret_resolver=secret_resolver)
    kwargs: dict[str, Any] = {
        "model": str(provider.get("model_id") or "").strip(),
        "api_key": api_key,
        "temperature": 0.2,
    }
    base_url = str(provider.get("base_url") or "").strip()
    if base_url:
        kwargs["base_url"] = _normalized_base_url(provider_type, base_url)
    if not kwargs["model"]:
        raise ValueError("Selected LLM provider has no model_id.")
    return ChatOpenAI(**kwargs)


def _build_ollama_chat_model(provider: dict[str, Any]) -> Any:
    try:
        from langchain_ollama import ChatOllama
    except ImportError as exc:
        raise RuntimeError("LangChain Ollama integration is not installed. Install gcs_server/requirements-gcs.txt.") from exc

    model_id = str(provider.get("model_id") or "").strip()
    if not model_id:
        raise ValueError("Selected Ollama provider has no model_id.")

    kwargs: dict[str, Any] = {
        "model": model_id,
        "temperature": 0.2,
    }
    base_url = str(provider.get("base_url") or "").strip()
    if base_url:
        kwargs["base_url"] = base_url.rstrip("/")
    return ChatOllama(**kwargs)


def _provider_from_routing(
    routing: dict[str, Any],
    providers: list[dict[str, Any]],
    purpose: str,
) -> dict[str, Any] | None:
    rule = routing.get(purpose, {}) if isinstance(routing, dict) else {}
    candidate_ids = []
    if isinstance(rule, dict):
        primary_id = str(rule.get("primary_provider_id", "")).strip()
        fallback_ids = [str(item).strip() for item in rule.get("fallback_provider_ids", []) if str(item).strip()]
        candidate_ids = [primary_id, *fallback_ids]
    for candidate_id in candidate_ids:
        provider = _find_provider(providers, candidate_id)
        if provider and provider.get("enabled", True):
            return provider
    return next((provider for provider in providers if provider.get("enabled", True)), None)


def _find_provider(providers: list[dict[str, Any]], provider_id: str) -> dict[str, Any] | None:
    return next((provider for provider in providers if str(provider.get("id")) == provider_id), None)


def _api_key_for_provider(provider: dict[str, Any], *, secret_resolver: Callable[[str], str] | None = None) -> str:
    auth_mode = str(provider.get("auth_mode", "env_var"))
    if auth_mode == "none":
        return "not-needed"
    if auth_mode == "stored_secret":
        secret_ref = str(provider.get("secret_ref", "")).strip()
        if not secret_ref:
            raise ValueError("Selected LLM provider has no secret_ref.")
        if secret_resolver is None:
            raise ValueError("Stored secret auth is not available in this runtime.")
        api_key = str(secret_resolver(secret_ref)).strip()
        if not api_key:
            raise ValueError("Stored secret value is empty.")
        return api_key
    secret_ref = str(provider.get("secret_ref", "")).strip()
    if not secret_ref:
        raise ValueError("Selected LLM provider has no secret_ref.")
    api_key = os.getenv(secret_ref, "").strip()
    if not api_key:
        raise ValueError(f"Environment variable {secret_ref} is not set.")
    return api_key


def _normalized_base_url(provider_type: str, base_url: str) -> str:
    if provider_type == "lm_studio":
        return base_url.rstrip("/")
    return base_url.rstrip("/")
