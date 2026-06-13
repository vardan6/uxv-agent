from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator
from uuid import uuid4

from .data_access import build_data_access_manifest
from .execution_mode import execution_tools_for_mode, resolve_execution_mode
from .policy_engine import POLICY_DENIED_STOP_REASON, PolicyEngine
from .tool_registry import DEFAULT_PERMISSIONS, EXECUTION
from .tool_result_cache import CACHEABLE_TOOL_NAMES, ToolResultCache


AI_AGENT_MAX_TOOL_ITERATIONS = 6
AI_AGENT_MAX_REPEATED_TOOL_FAILURES = 2
AI_AGENT_REPEATED_TOOL_FAILURE_MESSAGE = "I stopped because the same tool call failed repeatedly."


def _prompt_cache_enabled() -> bool:
    return os.getenv("AI_PROMPT_CACHE_DISABLED", "").strip().lower() not in {"1", "true", "yes"}


def _is_anthropic_model(model: Any) -> bool:
    """Detect ChatAnthropic (possibly wrapped by bind_tools) without importing langchain_anthropic."""
    candidate = model
    for attr in ("bound", "llm", "_llm", "model"):
        inner = getattr(candidate, attr, None)
        if inner is not None and inner is not candidate:
            candidate = inner
            break
    cls = type(candidate)
    if cls.__name__ == "ChatAnthropic":
        return True
    module = getattr(cls, "__module__", "") or ""
    return module.startswith("langchain_anthropic")


def _build_system_message(system_message_cls: Any, text: str, model: Any) -> Any:
    """Build a SystemMessage; mark it for Anthropic prompt caching when applicable.

    Anthropic charges full price on the first request and ~10% on subsequent requests
    that match the cached prefix (5-minute TTL). Marking the first system message with
    cache_control causes the entire prefix (tools + system) to be cached.
    OpenAI auto-caches identical prefixes server-side; no marker needed.
    Other providers receive a plain SystemMessage.
    """
    if not text:
        return system_message_cls(content="")
    if _prompt_cache_enabled() and _is_anthropic_model(model):
        return system_message_cls(
            content=[{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]
        )
    return system_message_cls(content=text)


@dataclass(slots=True)
class AgentInvokeResult:
    content: str
    tool_calls: list[dict[str, Any]]
    trace_events: list[dict[str, Any]]
    data_access_manifest: dict[str, Any]
    response_metadata: dict[str, Any]
    usage_metadata: dict[str, Any]
    stop_reason: str = "final_answer"
    iterations: int = 0
    trace_id: str = ""


@dataclass(slots=True)
class AgentToolRuntime:
    bound_model: Any
    tool_map: dict[str, Any]
    tool_definitions: dict[str, Any]
    langchain_messages: list[Any]
    tool_message_cls: Any
    permissions: frozenset[str]
    data_access_manifest: dict[str, Any]
    granted_scopes: frozenset[str]
    run_mode: str
    session_id: str = ""


class AgentLoopRuntime:
    def __init__(
        self,
        *,
        tool_registry: Any | None,
        prompt_builder: Callable[[dict[str, Any] | None, str, list[dict[str, Any]], list[Any] | None], str],
        system_prompt_for_mode: Callable[[str], str],
        allowed_tool_names: Callable[[dict[str, Any] | None], set[str] | None],
        response_content: Callable[[Any], str],
        usage_metadata: Callable[[Any], dict[str, Any]],
        tool_calling_unsupported: Callable[[Exception], bool],
        trace_store: Any | None = None,
        policy_engine: PolicyEngine | None = None,
    ):
        self._tool_registry = tool_registry
        self._prompt_builder = prompt_builder
        self._system_prompt_for_mode = system_prompt_for_mode
        self._allowed_tool_names = allowed_tool_names
        self._response_content = response_content
        self._usage_metadata = usage_metadata
        self._tool_calling_unsupported = tool_calling_unsupported
        self._trace_store = trace_store
        self._policy_engine = policy_engine or PolicyEngine()
        self._tool_result_cache = ToolResultCache()

    @property
    def tool_result_cache(self) -> ToolResultCache:
        return self._tool_result_cache

    def invoke_with_tools(
        self,
        model: Any,
        *,
        messages: list[dict[str, Any]],
        context_snapshot: dict[str, Any] | None,
        prompt_tool_calls: list[dict[str, Any]],
        tool_context: dict[str, Any] | None = None,
        run_mode: str = "agent",
    ) -> AgentInvokeResult | None:
        runtime = self.prepare_tool_runtime(
            model,
            messages=messages,
            context_snapshot=context_snapshot,
            prompt_tool_calls=prompt_tool_calls,
            tool_context=tool_context,
            run_mode=run_mode,
        )
        if runtime is None:
            return None

        trace_id = _new_trace_id()
        executed_tool_calls: list[dict[str, Any]] = []
        trace_events: list[dict[str, Any]] = []
        self._append_trace_event(trace_id, trace_events, {
            "type": "agent_run_start",
            "run_mode": run_mode,
            "max_iterations": AI_AGENT_MAX_TOOL_ITERATIONS,
            "max_repeated_tool_failures": AI_AGENT_MAX_REPEATED_TOOL_FAILURES,
        })
        final_response = None
        iterations = 0
        stop_reason = "iteration_limit"
        consecutive_failure_signature: str | None = None
        consecutive_failure_count = 0
        should_stop = False
        terminal_tool_error: dict[str, Any] | None = None

        for iteration in range(1, AI_AGENT_MAX_TOOL_ITERATIONS + 1):
            iterations = iteration
            self._append_trace_event(trace_id, trace_events, {"type": "agent_iteration_start", "iteration": iteration})
            try:
                final_response = runtime.bound_model.invoke(runtime.langchain_messages)
            except Exception as exc:
                if self._tool_calling_unsupported(exc):
                    return None
                raise
            runtime.langchain_messages.append(final_response)
            response_tool_calls = getattr(final_response, "tool_calls", None) or []
            if not response_tool_calls:
                stop_reason = "final_answer"
                break
            for call in response_tool_calls:
                tool_name = str(call.get("name") or "").strip()
                tool_args = call.get("args") if isinstance(call.get("args"), dict) else {}
                tool_call_id = str(call.get("id") or tool_name)
                self._append_trace_event(trace_id, trace_events, {
                    "type": "agent_tool_start",
                    "tool_call": {
                        "id": tool_call_id,
                        "name": tool_name,
                        "args": tool_args,
                        "iteration": iteration,
                    },
                })
                started = time.perf_counter()
                tool_result, policy_decision = self._invoke_tool(runtime, tool_name, tool_args)
                self._append_trace_event(trace_id, trace_events, {
                    "type": "agent_policy_decision",
                    "tool_call": {
                        "id": tool_call_id,
                        "name": tool_name,
                        "args": tool_args,
                        "iteration": iteration,
                    },
                    "policy_decision": policy_decision.as_trace_dict(),
                })
                latency_ms = int((time.perf_counter() - started) * 1000)
                failure_signature = _tool_failure_signature(tool_name, tool_args, tool_result)
                if failure_signature and failure_signature == consecutive_failure_signature:
                    consecutive_failure_count += 1
                elif failure_signature:
                    consecutive_failure_signature = failure_signature
                    consecutive_failure_count = 1
                else:
                    consecutive_failure_signature = None
                    consecutive_failure_count = 0
                executed_tool_calls.append(
                    {
                        "id": tool_call_id,
                        "name": tool_name,
                        "args": tool_args,
                        "result": tool_result,
                        "iteration": iteration,
                        "latency_ms": latency_ms,
                        "policy_decision": policy_decision.as_trace_dict(),
                    }
                )
                self._append_trace_event(trace_id, trace_events, {
                    "type": "agent_tool_result",
                    "tool_call": {
                        "id": tool_call_id,
                        "name": tool_name,
                        "args": tool_args,
                        "result": tool_result,
                        "iteration": iteration,
                        "latency_ms": latency_ms,
                        "policy_decision": policy_decision.as_trace_dict(),
                    },
                })
                definition = runtime.tool_definitions.get(tool_name)
                if definition is not None and getattr(definition, "is_terminal", False):
                    _handoff_type = (
                        isinstance(tool_result, dict)
                        and isinstance(tool_result.get("handoff"), dict)
                        and tool_result["handoff"].get("type")
                    )
                    if _handoff_type == "clarification_request":
                        stop_reason = "clarification_requested"
                    elif isinstance(tool_result, dict) and tool_result.get("ok") is False:
                        stop_reason = "terminal_tool_failed"
                    else:
                        stop_reason = "draft_proposed"
                    should_stop = True
                elif policy_decision.action != "allow":
                    stop_reason = policy_decision.stop_reason or POLICY_DENIED_STOP_REASON
                    should_stop = True
                    terminal_tool_error = {
                        "tool_name": tool_name,
                        "error": str(tool_result.get("error") or policy_decision.reason),
                    }
                if consecutive_failure_count >= AI_AGENT_MAX_REPEATED_TOOL_FAILURES:
                    stop_reason = "repeated_tool_failure"
                    self._append_trace_event(trace_id, trace_events, {
                        "type": "agent_repeated_tool_failure",
                        "tool_call": {
                            "id": tool_call_id,
                            "name": tool_name,
                            "args": tool_args,
                            "iteration": iteration,
                        },
                        "failure_count": consecutive_failure_count,
                    })
                    should_stop = True
                runtime.langchain_messages.append(
                    runtime.tool_message_cls(
                        content=json.dumps(tool_result, separators=(",", ":"), sort_keys=True),
                        tool_call_id=tool_call_id,
                        name=tool_name,
                    )
                )
                if should_stop:
                    break
            if should_stop:
                break

        if final_response is None:
            return None
        self._append_trace_event(trace_id, trace_events, {
            "type": "agent_run_end",
            "stop_reason": stop_reason,
            "iterations": iterations,
            "tool_call_count": len(executed_tool_calls),
        })
        return self._result_from_response(
            final_response,
            executed_tool_calls,
            trace_events,
            stop_reason,
            iterations,
            trace_id,
            runtime.data_access_manifest,
            terminal_tool_error,
        )

    def stream_tool_events(
        self,
        model: Any,
        *,
        messages: list[dict[str, Any]],
        context_snapshot: dict[str, Any] | None,
        prompt_tool_calls: list[dict[str, Any]],
        tool_context: dict[str, Any] | None = None,
        run_mode: str = "agent",
    ) -> Iterator[dict[str, Any]]:
        runtime = self.prepare_tool_runtime(
            model,
            messages=messages,
            context_snapshot=context_snapshot,
            prompt_tool_calls=prompt_tool_calls,
            tool_context=tool_context,
            run_mode=run_mode,
        )
        if runtime is None:
            yield {"type": "_agent_result", "result": None}
            return

        trace_id = _new_trace_id()
        executed_tool_calls: list[dict[str, Any]] = []
        trace_events: list[dict[str, Any]] = []
        self._append_trace_event(trace_id, trace_events, {
            "type": "agent_run_start",
            "run_mode": run_mode,
            "max_iterations": AI_AGENT_MAX_TOOL_ITERATIONS,
            "max_repeated_tool_failures": AI_AGENT_MAX_REPEATED_TOOL_FAILURES,
        })
        yield trace_events[-1]
        final_response = None
        iterations = 0
        stop_reason = "iteration_limit"
        consecutive_failure_signature: str | None = None
        consecutive_failure_count = 0
        should_stop = False
        terminal_tool_error: dict[str, Any] | None = None

        for iteration in range(1, AI_AGENT_MAX_TOOL_ITERATIONS + 1):
            iterations = iteration
            self._append_trace_event(trace_id, trace_events, {"type": "agent_iteration_start", "iteration": iteration})
            yield trace_events[-1]
            final_response = None
            try:
                for turn_event in self._stream_model_turn(runtime):
                    if turn_event.get("type") == "_turn_response":
                        final_response = turn_event.get("response")
                        continue
                    yield turn_event
            except Exception as exc:
                if self._tool_calling_unsupported(exc):
                    yield {"type": "_agent_result", "result": None}
                    return
                raise
            if final_response is None:
                # No chunks produced (or no stream support fell back to an empty
                # invoke); let the caller drop to plain non-tool generation.
                yield {"type": "_agent_result", "result": None}
                return
            runtime.langchain_messages.append(final_response)
            response_tool_calls = getattr(final_response, "tool_calls", None) or []
            if not response_tool_calls:
                stop_reason = "final_answer"
                break
            for call in response_tool_calls:
                tool_name = str(call.get("name") or "").strip()
                tool_args = call.get("args") if isinstance(call.get("args"), dict) else {}
                tool_call_id = str(call.get("id") or tool_name)
                started = time.perf_counter()
                self._append_trace_event(trace_id, trace_events, {
                    "type": "agent_tool_start",
                    "tool_call": {
                        "id": tool_call_id,
                        "name": tool_name,
                        "args": tool_args,
                        "iteration": iteration,
                    },
                })
                yield trace_events[-1]
                tool_result, policy_decision = self._invoke_tool(runtime, tool_name, tool_args)
                self._append_trace_event(trace_id, trace_events, {
                    "type": "agent_policy_decision",
                    "tool_call": {
                        "id": tool_call_id,
                        "name": tool_name,
                        "args": tool_args,
                        "iteration": iteration,
                    },
                    "policy_decision": policy_decision.as_trace_dict(),
                })
                yield trace_events[-1]
                failure_signature = _tool_failure_signature(tool_name, tool_args, tool_result)
                if failure_signature and failure_signature == consecutive_failure_signature:
                    consecutive_failure_count += 1
                elif failure_signature:
                    consecutive_failure_signature = failure_signature
                    consecutive_failure_count = 1
                else:
                    consecutive_failure_signature = None
                    consecutive_failure_count = 0
                executed_tool_call = {
                    "id": tool_call_id,
                    "name": tool_name,
                    "args": tool_args,
                    "result": tool_result,
                    "iteration": iteration,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "policy_decision": policy_decision.as_trace_dict(),
                }
                executed_tool_calls.append(executed_tool_call)
                self._append_trace_event(trace_id, trace_events, {
                    "type": "agent_tool_result",
                    "tool_call": dict(executed_tool_call),
                })
                yield trace_events[-1]
                definition = runtime.tool_definitions.get(tool_name)
                if definition is not None and getattr(definition, "is_terminal", False):
                    _handoff_type = (
                        isinstance(tool_result, dict)
                        and isinstance(tool_result.get("handoff"), dict)
                        and tool_result["handoff"].get("type")
                    )
                    if _handoff_type == "clarification_request":
                        stop_reason = "clarification_requested"
                    elif isinstance(tool_result, dict) and tool_result.get("ok") is False:
                        stop_reason = "terminal_tool_failed"
                    else:
                        stop_reason = "draft_proposed"
                    should_stop = True
                elif policy_decision.action != "allow":
                    stop_reason = policy_decision.stop_reason or POLICY_DENIED_STOP_REASON
                    should_stop = True
                    terminal_tool_error = {
                        "tool_name": tool_name,
                        "error": str(tool_result.get("error") or policy_decision.reason),
                    }
                if consecutive_failure_count >= AI_AGENT_MAX_REPEATED_TOOL_FAILURES:
                    stop_reason = "repeated_tool_failure"
                    self._append_trace_event(trace_id, trace_events, {
                        "type": "agent_repeated_tool_failure",
                        "tool_call": {
                            "id": tool_call_id,
                            "name": tool_name,
                            "args": tool_args,
                            "iteration": iteration,
                        },
                        "failure_count": consecutive_failure_count,
                    })
                    yield trace_events[-1]
                    should_stop = True
                runtime.langchain_messages.append(
                    runtime.tool_message_cls(
                        content=json.dumps(tool_result, separators=(",", ":"), sort_keys=True),
                        tool_call_id=tool_call_id,
                        name=tool_name,
                    )
                )
                if should_stop:
                    break
            if should_stop:
                break

        if final_response is None:
            yield {"type": "_agent_result", "result": None}
            return
        self._append_trace_event(trace_id, trace_events, {
            "type": "agent_run_end",
            "stop_reason": stop_reason,
            "iterations": iterations,
            "tool_call_count": len(executed_tool_calls),
        })
        yield trace_events[-1]
        yield {
            "type": "_agent_result",
            "result": self._result_from_response(
                final_response,
                executed_tool_calls,
                trace_events,
                stop_reason,
                iterations,
                trace_id,
                runtime.data_access_manifest,
                terminal_tool_error,
            ),
        }

    def _stream_model_turn(self, runtime: AgentToolRuntime) -> Iterator[dict[str, Any]]:
        """Stream one bound-model turn, surfacing text deltas as they arrive.

        Yields ``{"type": "assistant_delta", "delta": text}`` for each text chunk so the
        agent's final answer reaches the client token-by-token instead of being buffered
        until the whole turn (and any tool round-trips) complete. The accumulated chunk —
        which still carries ``tool_calls`` and response/usage metadata — is returned via a
        final ``{"type": "_turn_response", "response": ...}`` event so the loop can decide
        whether more tool calls are needed, exactly as the blocking path did.

        Only the streaming entry path uses this; ``invoke_with_tools`` keeps using a plain
        blocking ``.invoke`` so a provider that streams tool calls poorly cannot regress the
        non-streaming path.
        """
        stream = getattr(runtime.bound_model, "stream", None)
        if not callable(stream):
            yield {"type": "_turn_response", "response": runtime.bound_model.invoke(runtime.langchain_messages)}
            return
        gathered: Any = None
        for chunk in stream(runtime.langchain_messages):
            gathered = chunk if gathered is None else gathered + chunk
            delta = self._response_content(chunk)
            if delta:
                yield {"type": "assistant_delta", "delta": delta}
        yield {"type": "_turn_response", "response": gathered}

    def prepare_tool_runtime(
        self,
        model: Any,
        *,
        messages: list[dict[str, Any]],
        context_snapshot: dict[str, Any] | None,
        prompt_tool_calls: list[dict[str, Any]],
        tool_context: dict[str, Any] | None = None,
        run_mode: str = "agent",
    ) -> AgentToolRuntime | None:
        if self._tool_registry is None:
            return None
        bind_tools = getattr(model, "bind_tools", None)
        if not callable(bind_tools):
            return None

        try:
            from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
        except ImportError as exc:
            raise RuntimeError("LangChain core is not installed. Install gcs_server/requirements-gcs.txt.") from exc

        ctx = tool_context or {}
        runtime = ctx.get("runtime")
        timezone_name = str(ctx.get("timezone_name") or "").strip()
        # EXECUTION is granted at the permission layer so the mode-bound execution
        # tools can build and pass policy; the per-mode filter below (and Strict's
        # empty arm/execute set) is what actually decides which execution tools the
        # model sees. COMMAND_STAGING stays disabled in the registry.
        permissions = frozenset(DEFAULT_PERMISSIONS | {EXECUTION})
        tools = self._tool_registry.build_langchain_tools(
            runtime,
            context_snapshot or {},
            timezone_name=timezone_name,
            permissions=set(permissions),
        )
        allowed_names = self._allowed_tool_names(context_snapshot)
        if allowed_names is not None:
            tools = [tool for tool in tools if str(getattr(tool, "name", "")) in allowed_names]
        definitions = self._tool_registry.definitions()
        definition_map = {definition.name: definition for definition in definitions}
        # ADR 0021 §1: gate execution-tier tools by the resolved execution mode.
        # Strict binds neither arm nor execute; Confirm binds arm_execution;
        # Autonomous binds execute_mission; cancel/abort always bind. Execution
        # tools land with the Phase 3 executor, so this is a no-op until then.
        execution_mode = resolve_execution_mode(getattr(runtime, "config", None)) if runtime is not None else "strict"
        mode_bound_execution = execution_tools_for_mode(execution_mode)
        tools = [
            tool
            for tool in tools
            if getattr(definition_map.get(str(getattr(tool, "name", ""))), "permission", None) != EXECUTION
            or str(getattr(tool, "name", "")) in mode_bound_execution
        ]
        if not tools:
            return None
        manifest = build_data_access_manifest(definitions, allowed_tool_names=allowed_names)

        try:
            # OpenAI Responses normalizes omitted tool strictness into strict mode,
            # which breaks our optional tool arguments (for example max_distance_m).
            bound_model = bind_tools(tools, strict=False)
        except Exception as exc:
            if self._tool_calling_unsupported(exc):
                return None
            raise

        langchain_messages = [
            _build_system_message(SystemMessage, self._system_prompt_for_mode(run_mode), model)
        ]
        context_prompt = self._prompt_builder(context_snapshot, run_mode, prompt_tool_calls, tools, manifest)
        if context_prompt:
            # Per-turn dynamic context (rover pose, telemetry, tool results); not cached.
            langchain_messages.append(SystemMessage(content=context_prompt))
        for message in messages:
            role = message.get("role")
            content = str(message.get("content") or "")
            if role == "user":
                langchain_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                langchain_messages.append(AIMessage(content=content))

        session_id = str(ctx.get("session_id") or "").strip()
        return AgentToolRuntime(
            bound_model=bound_model,
            tool_map={str(tool.name): tool for tool in tools},
            tool_definitions=definition_map,
            langchain_messages=langchain_messages,
            tool_message_cls=ToolMessage,
            permissions=permissions,
            data_access_manifest=manifest,
            granted_scopes=frozenset(),
            run_mode=run_mode,
            session_id=session_id,
        )

    def _invoke_tool(self, runtime: AgentToolRuntime, tool_name: str, tool_args: dict[str, Any]) -> tuple[Any, Any]:
        definition = runtime.tool_definitions.get(tool_name)
        policy_decision = self._policy_engine.evaluate(
            definition=definition,
            tool_name=tool_name,
            available_permissions=runtime.permissions,
            granted_scopes=runtime.granted_scopes,
            run_mode=runtime.run_mode,
        )
        if policy_decision.action != "allow":
            return {"ok": False, "error": policy_decision.reason}, policy_decision
        tool = runtime.tool_map.get(tool_name)
        if tool is None:
            fallback = self._policy_engine.evaluate(
                definition=None,
                tool_name=tool_name,
                available_permissions=runtime.permissions,
                granted_scopes=runtime.granted_scopes,
                run_mode=runtime.run_mode,
            )
            return {"ok": False, "error": f"tool '{tool_name}' is not available"}, fallback
        # Cache lookup for read-only, session-stable tools (see tool_result_cache.CACHEABLE_TOOL_NAMES).
        if tool_name in CACHEABLE_TOOL_NAMES and runtime.session_id:
            cached = self._tool_result_cache.get(runtime.session_id, tool_name, tool_args)
            if cached is not None:
                return cached, policy_decision
        try:
            result = tool.invoke(tool_args)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}, policy_decision
        if tool_name in CACHEABLE_TOOL_NAMES and runtime.session_id:
            self._tool_result_cache.set(runtime.session_id, tool_name, tool_args, result)
        return result, policy_decision

    def _result_from_response(
        self,
        response: Any,
        executed_tool_calls: list[dict[str, Any]],
        trace_events: list[dict[str, Any]],
        stop_reason: str,
        iterations: int,
        trace_id: str,
        data_access_manifest: dict[str, Any],
        terminal_tool_error: dict[str, Any] | None = None,
    ) -> AgentInvokeResult:
        content = self._response_content(response)
        if stop_reason == "repeated_tool_failure" and not content.strip():
            content = _repeated_tool_failure_message(executed_tool_calls)
        if stop_reason == POLICY_DENIED_STOP_REASON and not content.strip():
            content = _policy_denied_message(executed_tool_calls, terminal_tool_error)
        return AgentInvokeResult(
            content=content,
            tool_calls=executed_tool_calls,
            trace_events=trace_events,
            data_access_manifest=data_access_manifest,
            response_metadata=getattr(response, "response_metadata", {}) or {},
            usage_metadata=self._usage_metadata(response),
            stop_reason=stop_reason,
            iterations=iterations,
            trace_id=trace_id,
        )

    def _append_trace_event(
        self,
        trace_id: str,
        trace_events: list[dict[str, Any]],
        event: dict[str, Any],
    ) -> None:
        payload = dict(event)
        payload.setdefault("trace_id", trace_id)
        payload.setdefault("ts", time.time())
        trace_events.append(payload)
        if self._trace_store is None:
            return
        try:
            self._trace_store.append(trace_id, payload)
        except Exception as exc:
            trace_events.append({
                "type": "agent_trace_write_error",
                "trace_id": trace_id,
                "ts": time.time(),
                "error": str(exc),
            })


def _new_trace_id() -> str:
    return f"agt-{uuid4().hex}"


def _tool_failure_signature(tool_name: str, tool_args: dict[str, Any], tool_result: Any) -> str | None:
    if not _is_tool_failure(tool_result):
        return None
    try:
        args_json = json.dumps(tool_args, sort_keys=True, separators=(",", ":"))
    except TypeError:
        args_json = repr(sorted((str(key), repr(value)) for key, value in tool_args.items()))
    return f"{tool_name}:{args_json}"


def _is_tool_failure(tool_result: Any) -> bool:
    return isinstance(tool_result, dict) and (tool_result.get("ok") is False or bool(tool_result.get("error")))


def _repeated_tool_failure_message(executed_tool_calls: list[dict[str, Any]]) -> str:
    if not executed_tool_calls:
        return AI_AGENT_REPEATED_TOOL_FAILURE_MESSAGE
    last_call = executed_tool_calls[-1]
    tool_name = str(last_call.get("name") or "tool")
    result = last_call.get("result")
    error = ""
    if isinstance(result, dict):
        error = str(result.get("error") or "").strip()
    if not error:
        return f"{AI_AGENT_REPEATED_TOOL_FAILURE_MESSAGE} Tool: {tool_name}."
    return f"{AI_AGENT_REPEATED_TOOL_FAILURE_MESSAGE} Tool: {tool_name}. Error: {error}"


def _policy_denied_message(executed_tool_calls: list[dict[str, Any]], terminal_tool_error: dict[str, Any] | None) -> str:
    tool_name = str((terminal_tool_error or {}).get("tool_name") or "")
    error = str((terminal_tool_error or {}).get("error") or "").strip()
    if not tool_name and executed_tool_calls:
        tool_name = str(executed_tool_calls[-1].get("name") or "")
    if not error and executed_tool_calls:
        result = executed_tool_calls[-1].get("result")
        if isinstance(result, dict):
            error = str(result.get("error") or "").strip()
    if tool_name and error:
        return f"I stopped because policy blocked tool `{tool_name}`. Reason: {error}"
    if tool_name:
        return f"I stopped because policy blocked tool `{tool_name}`."
    return "I stopped because a tool call was blocked by policy."
