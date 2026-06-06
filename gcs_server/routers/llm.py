from __future__ import annotations

import asyncio
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request as UrlRequest, urlopen

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from gcs_server.ai.provider_registry import evict_model_cache
from gcs_server.config import save_config
from gcs_server.provider_normalizers import (
    ROUTING_PURPOSES,
    _normalize_provider,
    _normalize_routing,
    _sanitize_secret_ref,
    _sanitize_stored_secret_ref,
)
from gcs_server.runtime import AppRuntime

router = APIRouter()


def _runtime(request: Request) -> AppRuntime:
    return request.app.state.runtime


def _redact_secret_text(value: Any) -> str:
    return re.sub(
        r"\b([A-Za-z_][A-Za-z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)[A-Za-z0-9_]*)=([^\s,;]+)",
        r"\1=********",
        str(value or ""),
        flags=re.IGNORECASE,
    )


def _provider_public(provider: dict[str, Any], runtime: AppRuntime | None = None) -> dict[str, Any]:
    out = dict(provider)
    auth_mode = str(out.get("auth_mode", "env_var")).strip()
    if auth_mode == "stored_secret":
        out["secret_ref"] = _sanitize_stored_secret_ref(out.get("secret_ref", ""))
        out["has_secret"] = bool(
            runtime
            and out["secret_ref"]
            and runtime.secret_store.has_secret(out["secret_ref"])
        )
    else:
        out["secret_ref"] = _sanitize_secret_ref(out.get("secret_ref", ""))
        out["has_secret"] = False
    out.pop("secret_value", None)
    last_check = out.get("last_check")
    if isinstance(last_check, dict):
        redacted_check = dict(last_check)
        if "message" in redacted_check:
            redacted_check["message"] = _redact_secret_text(redacted_check["message"])
        out["last_check"] = redacted_check
    return out


def _repair_stored_secret_refs(config: Any) -> bool:
    providers = config.raw.get("llm_providers", [])
    if not isinstance(providers, list):
        return False
    changed = False
    for index, provider in enumerate(providers):
        if not isinstance(provider, dict):
            continue
        auth_mode = str(provider.get("auth_mode", "")).strip()
        if auth_mode != "stored_secret":
            continue
        if _sanitize_stored_secret_ref(provider.get("secret_ref", "")):
            continue
        try:
            normalized = _normalize_provider(provider, provider)
        except HTTPException:
            continue
        if normalized != provider:
            providers[index] = normalized
            changed = True
    return changed


def _find_provider(runtime: AppRuntime, provider_id: str) -> tuple[int, dict[str, Any]]:
    providers = runtime.config.raw.setdefault("llm_providers", [])
    if not isinstance(providers, list):
        runtime.config.raw["llm_providers"] = []
        providers = runtime.config.raw["llm_providers"]
    for index, provider in enumerate(providers):
        if isinstance(provider, dict) and provider.get("id") == provider_id:
            return index, provider
    raise HTTPException(status_code=404, detail="provider not found")


def _http_json_probe(url: str, secret: str | None = None) -> tuple[bool, str]:
    headers = {"Accept": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    request = UrlRequest(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=8) as response:
            if 200 <= response.status < 300:
                return True, f"HTTP {response.status}"
            return False, f"HTTP {response.status}"
    except HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except URLError as exc:
        return False, str(exc.reason)
    except TimeoutError:
        return False, "request timed out"


def _check_provider(runtime: AppRuntime, provider: dict[str, Any], secret_override: str | None = None) -> dict[str, Any]:
    auth_mode = str(provider.get("auth_mode", "")).strip()
    if auth_mode == "env_var":
        secret_ref = str(provider.get("secret_ref", "")).strip()
        if not secret_ref:
            return {"status": "missing_key", "ok": False, "message": "missing environment variable name"}
        secret = os.environ.get(secret_ref)
        if not secret:
            return {"status": "missing_key", "ok": False, "message": f"environment variable {secret_ref} is not set"}
    elif auth_mode == "stored_secret":
        if secret_override is not None:
            secret = secret_override
        else:
            secret_ref = _sanitize_stored_secret_ref(provider.get("secret_ref", ""))
            if not secret_ref:
                return {"status": "missing_key", "ok": False, "message": "stored secret reference is missing"}
            try:
                secret = runtime.secret_store.get_secret(secret_ref)
            except KeyError:
                return {"status": "missing_key", "ok": False, "message": "stored API key is not set"}
        if not secret:
            return {"status": "missing_key", "ok": False, "message": "stored API key is empty"}
    else:
        secret = None

    provider_type = str(provider.get("provider_type", ""))
    base_url = str(provider.get("base_url", "")).strip()
    if provider_type == "ollama":
        probe_url = urljoin(base_url.rstrip("/") + "/", "api/tags") if base_url else "http://localhost:11434/api/tags"
    else:
        if not base_url:
            return {"status": "invalid", "ok": False, "message": "base_url is required"}
        probe_url = urljoin(base_url.rstrip("/") + "/", "models")

    ok, message = _http_json_probe(probe_url, secret)
    return {
        "status": "available" if ok else "unavailable",
        "ok": ok,
        "message": message,
        "checked_url": probe_url,
    }


def _default_routing(providers: list[dict[str, Any]]) -> dict[str, Any]:
    enabled_ids = [str(provider.get("id")) for provider in providers if isinstance(provider, dict) and provider.get("enabled", True)]
    first = enabled_ids[0] if enabled_ids else ""
    return {
        purpose: {
            "primary_provider_id": first,
            "fallback_provider_ids": enabled_ids[1:3],
            "allow_runtime_override": True,
        }
        for purpose in ROUTING_PURPOSES
    }


def _sanitize_routing(payload: dict[str, Any] | None, providers: list[dict[str, Any]]) -> dict[str, Any]:
    raw_payload = payload if isinstance(payload, dict) else {}
    provider_ids = {str(provider.get("id")) for provider in providers if isinstance(provider, dict)}
    normalized_payload: dict[str, Any] = {}
    for purpose in ROUTING_PURPOSES:
        raw_rule = raw_payload.get(purpose, {})
        if not isinstance(raw_rule, dict):
            raw_rule = {}
        primary_id = str(raw_rule.get("primary_provider_id", "")).strip()
        fallback_ids = [str(item).strip() for item in raw_rule.get("fallback_provider_ids", []) if str(item).strip()]
        normalized_payload[purpose] = {
            "primary_provider_id": primary_id if primary_id in provider_ids else "",
            "fallback_provider_ids": [item for item in fallback_ids if item in provider_ids],
            "allow_runtime_override": bool(raw_rule.get("allow_runtime_override", True)),
        }
    normalized = _normalize_routing(normalized_payload, providers)
    enabled_ids = [
        str(provider.get("id"))
        for provider in providers
        if isinstance(provider, dict) and provider.get("enabled", True)
    ]
    enabled_id_set = set(enabled_ids)
    first_enabled = enabled_ids[0] if enabled_ids else ""
    out: dict[str, Any] = {}
    for purpose in ROUTING_PURPOSES:
        rule = normalized.get(purpose, {})
        candidate_ids = []
        if isinstance(rule, dict):
            candidate_ids = [
                str(rule.get("primary_provider_id", "")).strip(),
                *[str(item).strip() for item in rule.get("fallback_provider_ids", []) if str(item).strip()],
            ]
        ordered_enabled_ids: list[str] = []
        for candidate_id in candidate_ids:
            if candidate_id and candidate_id in enabled_id_set and candidate_id not in ordered_enabled_ids:
                ordered_enabled_ids.append(candidate_id)
        primary_id = ordered_enabled_ids[0] if ordered_enabled_ids else first_enabled
        fallback_ids = [candidate_id for candidate_id in ordered_enabled_ids[1:] if candidate_id != primary_id]
        out[purpose] = {
            "primary_provider_id": primary_id,
            "fallback_provider_ids": fallback_ids,
            "allow_runtime_override": bool(rule.get("allow_runtime_override", True)) if isinstance(rule, dict) else True,
        }
    return out


@router.get("/api/llm-providers")
async def get_llm_providers(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    providers = runtime.config.raw.setdefault("llm_providers", [])
    if not isinstance(providers, list):
        runtime.config.raw["llm_providers"] = []
        providers = runtime.config.raw["llm_providers"]
    return {"providers": [_provider_public(provider, runtime) for provider in providers if isinstance(provider, dict)]}


@router.post("/api/llm-providers")
async def create_llm_provider(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="provider payload must be an object")
    provider = _normalize_provider(payload)
    secret_value = str(payload.get("secret_value", "")).strip()
    if provider.get("auth_mode") == "stored_secret":
        if not secret_value:
            raise HTTPException(status_code=400, detail="secret_value is required for stored_secret auth")
        runtime.secret_store.set_secret(str(provider.get("secret_ref", "")), secret_value)
    providers = runtime.config.raw.setdefault("llm_providers", [])
    if not isinstance(providers, list):
        runtime.config.raw["llm_providers"] = []
        providers = runtime.config.raw["llm_providers"]
    providers.append(provider)
    runtime.config.raw["model_routing"] = _sanitize_routing(runtime.config.raw.get("model_routing"), providers)
    save_config(runtime.config)
    evict_model_cache()
    return JSONResponse({
        "ok": True,
        "provider": _provider_public(provider, runtime),
        "routing": runtime.config.raw["model_routing"],
    })


@router.put("/api/llm-providers/{provider_id}")
async def update_llm_provider(provider_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="provider payload must be an object")
    index, current = _find_provider(runtime, provider_id)
    provider = _normalize_provider(payload, current)
    provider["id"] = provider_id
    previous_auth_mode = str(current.get("auth_mode", "")).strip()
    previous_secret_ref = str(current.get("secret_ref", "")).strip()
    secret_value = str(payload.get("secret_value", "")).strip()
    if provider.get("auth_mode") == "stored_secret":
        if secret_value:
            runtime.secret_store.set_secret(str(provider.get("secret_ref", "")), secret_value)
        elif not runtime.secret_store.has_secret(str(provider.get("secret_ref", ""))):
            raise HTTPException(status_code=400, detail="secret_value is required for stored_secret auth")
    if previous_auth_mode == "stored_secret" and provider.get("auth_mode") != "stored_secret" and previous_secret_ref:
        runtime.secret_store.delete_secret(previous_secret_ref)
    runtime.config.raw["llm_providers"][index] = provider
    runtime.config.raw["model_routing"] = _sanitize_routing(
        runtime.config.raw.get("model_routing"),
        [item for item in runtime.config.raw["llm_providers"] if isinstance(item, dict)],
    )
    save_config(runtime.config)
    evict_model_cache()
    return JSONResponse({
        "ok": True,
        "provider": _provider_public(provider, runtime),
        "routing": runtime.config.raw["model_routing"],
    })


@router.delete("/api/llm-providers/{provider_id}")
async def delete_llm_provider(provider_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    index, provider = _find_provider(runtime, provider_id)
    del runtime.config.raw["llm_providers"][index]
    preserved = runtime.ai_store.preserve_deleted_provider_history(provider)
    runtime.ai_store.clear_provider_selection(provider_id)
    if str(provider.get("auth_mode", "")).strip() == "stored_secret":
        runtime.secret_store.delete_secret(str(provider.get("secret_ref", "")).strip())
    runtime.config.raw["model_routing"] = _sanitize_routing(
        runtime.config.raw.get("model_routing"),
        [item for item in runtime.config.raw["llm_providers"] if isinstance(item, dict)],
    )
    save_config(runtime.config)
    evict_model_cache()
    return JSONResponse({
        "ok": True,
        "deleted_provider_id": provider_id,
        "provider": _provider_public(provider, runtime),
        "preserved_history": preserved,
        "routing": runtime.config.raw["model_routing"],
    })


@router.post("/api/llm-providers/{provider_id}/check")
async def check_llm_provider(provider_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    index, provider = _find_provider(runtime, provider_id)
    loop = asyncio.get_running_loop()
    check = await loop.run_in_executor(None, _check_provider, runtime, provider)
    provider["last_check"] = check
    runtime.config.raw["llm_providers"][index] = provider
    save_config(runtime.config)
    return JSONResponse({"ok": check["ok"], "provider": _provider_public(provider, runtime), "check": check})


@router.post("/api/llm-providers/check-draft")
async def check_llm_provider_draft(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="provider payload must be an object")
    provider = _normalize_provider(payload)
    secret_value = str(payload.get("secret_value", "")).strip()
    draft_secret_override = None
    if provider.get("auth_mode") == "stored_secret":
        if not secret_value:
            return JSONResponse(
                {
                    "ok": False,
                    "provider": _provider_public(provider, runtime),
                    "check": {"status": "missing_key", "ok": False, "message": "stored API key is required for draft check"},
                }
            )
        draft_secret_override = secret_value
    loop = asyncio.get_running_loop()
    check = await loop.run_in_executor(None, _check_provider, runtime, provider, draft_secret_override)
    provider["last_check"] = check
    return JSONResponse({"ok": check["ok"], "provider": _provider_public(provider, runtime), "check": check})


@router.get("/api/model-routing")
async def get_model_routing(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    providers = [provider for provider in runtime.config.raw.setdefault("llm_providers", []) if isinstance(provider, dict)]
    current = runtime.config.raw.setdefault("model_routing", {})
    routing = _sanitize_routing(current, providers) if current else _default_routing(providers)
    if routing != current:
        runtime.config.raw["model_routing"] = routing
        save_config(runtime.config)
    return {"purposes": ROUTING_PURPOSES, "routing": routing}


@router.put("/api/model-routing")
async def set_model_routing(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    routing_payload = payload.get("routing") if isinstance(payload, dict) else None
    if not isinstance(routing_payload, dict):
        raise HTTPException(status_code=400, detail="routing object is required")
    providers = [provider for provider in runtime.config.raw.setdefault("llm_providers", []) if isinstance(provider, dict)]
    routing = _sanitize_routing(routing_payload, providers)
    runtime.config.raw["model_routing"] = routing
    save_config(runtime.config)
    return JSONResponse({"ok": True, "purposes": ROUTING_PURPOSES, "routing": routing})


@router.get("/api/llm-settings")
async def get_llm_settings(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    providers = [provider for provider in runtime.config.raw.setdefault("llm_providers", []) if isinstance(provider, dict)]
    routing = runtime.config.raw.setdefault("model_routing", {})
    routing = _sanitize_routing(routing, providers) if routing else _default_routing(providers)
    if routing != runtime.config.raw.get("model_routing"):
        runtime.config.raw["model_routing"] = routing
        save_config(runtime.config)
    return {
        "providers": [_provider_public(provider, runtime) for provider in providers],
        "purposes": ROUTING_PURPOSES,
        "routing": routing,
    }


@router.put("/api/llm-settings")
async def set_llm_settings(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="settings payload must be an object")
    providers_payload = payload.get("llm_providers", payload.get("providers", []))
    if not isinstance(providers_payload, list):
        raise HTTPException(status_code=400, detail="llm_providers must be a list")
    existing_providers = {
        str(p.get("id", "")): p
        for p in runtime.config.raw.get("llm_providers", [])
        if isinstance(p, dict)
    }
    providers = [
        _normalize_provider(provider, existing_providers.get(str(provider.get("id", ""))))
        for provider in providers_payload
        if isinstance(provider, dict)
    ]
    routing_payload = payload.get("model_routing", payload.get("routing", {}))
    if not isinstance(routing_payload, dict):
        raise HTTPException(status_code=400, detail="model_routing must be an object")
    runtime.config.raw["llm_providers"] = providers
    runtime.config.raw["model_routing"] = _sanitize_routing(routing_payload, providers) if routing_payload else _default_routing(providers)
    save_config(runtime.config)
    return JSONResponse({
        "ok": True,
        "providers": [_provider_public(provider, runtime) for provider in providers],
        "routing": runtime.config.raw["model_routing"],
    })
