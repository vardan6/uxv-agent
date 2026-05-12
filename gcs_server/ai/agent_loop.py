from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from .tool_registry import DEFAULT_PERMISSIONS


AI_AGENT_MAX_TOOL_ITERATIONS = 6


@dataclass(slots=True)
class AgentInvokeResult:
    content: str
    tool_calls: list[dict[str, Any]]
    trace_events: list[dict[str, Any]]
    response_metadata: dict[str, Any]
    usage_metadata: dict[str, Any]
    stop_reason: str = "final_answer"
    iterations: int = 0


@dataclass(slots=True)
class AgentToolRuntime:
    bound_model: Any
    tool_map: dict[str, Any]
    langchain_messages: list[Any]
    tool_message_cls: Any


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
    ):
        self._tool_registry = tool_registry
        self._prompt_builder = prompt_builder
        self._system_prompt_for_mode = system_prompt_for_mode
        self._allowed_tool_names = allowed_tool_names
        self._response_content = response_content
        self._usage_metadata = usage_metadata
        self._tool_calling_unsupported = tool_calling_unsupported

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

        executed_tool_calls: list[dict[str, Any]] = []
        trace_events: list[dict[str, Any]] = [{
            "type": "agent_run_start",
            "run_mode": run_mode,
            "max_iterations": AI_AGENT_MAX_TOOL_ITERATIONS,
        }]
        final_response = None
        iterations = 0
        stop_reason = "iteration_limit"

        for iteration in range(1, AI_AGENT_MAX_TOOL_ITERATIONS + 1):
            iterations = iteration
            trace_events.append({"type": "agent_iteration_start", "iteration": iteration})
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
                trace_events.append({
                    "type": "agent_tool_start",
                    "tool_call": {
                        "id": tool_call_id,
                        "name": tool_name,
                        "args": tool_args,
                        "iteration": iteration,
                    },
                })
                started = time.perf_counter()
                tool_result = self._invoke_tool(runtime, tool_name, tool_args)
                latency_ms = int((time.perf_counter() - started) * 1000)
                executed_tool_calls.append(
                    {
                        "id": tool_call_id,
                        "name": tool_name,
                        "args": tool_args,
                        "result": tool_result,
                        "iteration": iteration,
                        "latency_ms": latency_ms,
                    }
                )
                trace_events.append({
                    "type": "agent_tool_result",
                    "tool_call": {
                        "id": tool_call_id,
                        "name": tool_name,
                        "args": tool_args,
                        "result": tool_result,
                        "iteration": iteration,
                        "latency_ms": latency_ms,
                    },
                })
                runtime.langchain_messages.append(
                    runtime.tool_message_cls(
                        content=json.dumps(tool_result, separators=(",", ":"), sort_keys=True),
                        tool_call_id=tool_call_id,
                        name=tool_name,
                    )
                )

        if final_response is None:
            return None
        trace_events.append({
            "type": "agent_run_end",
            "stop_reason": stop_reason,
            "iterations": iterations,
            "tool_call_count": len(executed_tool_calls),
        })
        return self._result_from_response(final_response, executed_tool_calls, trace_events, stop_reason, iterations)

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

        executed_tool_calls: list[dict[str, Any]] = []
        trace_events: list[dict[str, Any]] = [{
            "type": "agent_run_start",
            "run_mode": run_mode,
            "max_iterations": AI_AGENT_MAX_TOOL_ITERATIONS,
        }]
        yield trace_events[-1]
        final_response = None
        iterations = 0
        stop_reason = "iteration_limit"

        for iteration in range(1, AI_AGENT_MAX_TOOL_ITERATIONS + 1):
            iterations = iteration
            trace_events.append({"type": "agent_iteration_start", "iteration": iteration})
            yield trace_events[-1]
            try:
                final_response = runtime.bound_model.invoke(runtime.langchain_messages)
            except Exception as exc:
                if self._tool_calling_unsupported(exc):
                    yield {"type": "_agent_result", "result": None}
                    return
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
                started = time.perf_counter()
                trace_events.append({
                    "type": "agent_tool_start",
                    "tool_call": {
                        "id": tool_call_id,
                        "name": tool_name,
                        "args": tool_args,
                        "iteration": iteration,
                    },
                })
                yield trace_events[-1]
                tool_result = self._invoke_tool(runtime, tool_name, tool_args)
                executed_tool_call = {
                    "id": tool_call_id,
                    "name": tool_name,
                    "args": tool_args,
                    "result": tool_result,
                    "iteration": iteration,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                }
                executed_tool_calls.append(executed_tool_call)
                trace_events.append({
                    "type": "agent_tool_result",
                    "tool_call": dict(executed_tool_call),
                })
                yield trace_events[-1]
                runtime.langchain_messages.append(
                    runtime.tool_message_cls(
                        content=json.dumps(tool_result, separators=(",", ":"), sort_keys=True),
                        tool_call_id=tool_call_id,
                        name=tool_name,
                    )
                )

        if final_response is None:
            yield {"type": "_agent_result", "result": None}
            return
        trace_events.append({
            "type": "agent_run_end",
            "stop_reason": stop_reason,
            "iterations": iterations,
            "tool_call_count": len(executed_tool_calls),
        })
        yield trace_events[-1]
        yield {
            "type": "_agent_result",
            "result": self._result_from_response(final_response, executed_tool_calls, trace_events, stop_reason, iterations),
        }

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
        tools = self._tool_registry.build_langchain_tools(
            runtime,
            context_snapshot or {},
            timezone_name=timezone_name,
            permissions=set(DEFAULT_PERMISSIONS),
        )
        allowed_names = self._allowed_tool_names(context_snapshot)
        if allowed_names is not None:
            tools = [tool for tool in tools if str(getattr(tool, "name", "")) in allowed_names]
        if not tools:
            return None

        try:
            # OpenAI Responses normalizes omitted tool strictness into strict mode,
            # which breaks our optional tool arguments (for example max_distance_m).
            bound_model = bind_tools(tools, strict=False)
        except Exception as exc:
            if self._tool_calling_unsupported(exc):
                return None
            raise

        langchain_messages = [SystemMessage(content=self._system_prompt_for_mode(run_mode))]
        context_prompt = self._prompt_builder(context_snapshot, run_mode, prompt_tool_calls, tools)
        if context_prompt:
            langchain_messages.append(SystemMessage(content=context_prompt))
        for message in messages:
            role = message.get("role")
            content = str(message.get("content") or "")
            if role == "user":
                langchain_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                langchain_messages.append(AIMessage(content=content))

        return AgentToolRuntime(
            bound_model=bound_model,
            tool_map={str(tool.name): tool for tool in tools},
            langchain_messages=langchain_messages,
            tool_message_cls=ToolMessage,
        )

    def _invoke_tool(self, runtime: AgentToolRuntime, tool_name: str, tool_args: dict[str, Any]) -> Any:
        tool = runtime.tool_map.get(tool_name)
        if tool is None:
            return {"ok": False, "error": f"tool '{tool_name}' is not available"}
        try:
            return tool.invoke(tool_args)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _result_from_response(
        self,
        response: Any,
        executed_tool_calls: list[dict[str, Any]],
        trace_events: list[dict[str, Any]],
        stop_reason: str,
        iterations: int,
    ) -> AgentInvokeResult:
        return AgentInvokeResult(
            content=self._response_content(response),
            tool_calls=executed_tool_calls,
            trace_events=trace_events,
            response_metadata=getattr(response, "response_metadata", {}) or {},
            usage_metadata=self._usage_metadata(response),
            stop_reason=stop_reason,
            iterations=iterations,
        )
