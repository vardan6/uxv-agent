#!/usr/bin/env python3
"""GCS AI CLI — thin terminal client over the GCS /api/ai/... backend."""

import argparse
import json
import os
import sys

try:
    import httpx
except ImportError:
    print("gcs-ai requires httpx. Run: pip install httpx", file=sys.stderr)
    sys.exit(1)

_EXIT_TRANSPORT = 1   # GCS unreachable, timeout, connection refused
_EXIT_USAGE = 2       # bad CLI arguments
_EXIT_BACKEND_4XX = 3 # backend rejected the request (404, 400, etc.)
_EXIT_PROVIDER = 4    # backend/provider execution failure (5xx, empty response)

# Maps CLI slash form → backend "command" string for POST /api/ai/.../commands
_SESSION_COMMANDS: dict[str, str] = {
    "/capabilities brief": "capabilities brief",
    "/capabilities full": "capabilities full",
    "/retrieval-surfaces": "retrieval-surfaces",
    "/tool-activity": "tool-activity",
    "/context": "context",
}


def _die(code: int, msg: str) -> None:
    print(f"gcs-ai: {msg}", file=sys.stderr)
    sys.exit(code)


def _fmt_tokens(n) -> str:
    """Mirror the web UI fmtTokens(): compact K-suffix token counts."""
    try:
        value = float(n)
    except (TypeError, ValueError):
        return ""
    if value < 0:
        return ""
    if value >= 10000:
        return f"{round(value / 1000)}K"
    if value >= 1000:
        return f"{value / 1000:.1f}K"
    return str(round(value))


def _fmt_tok_per_sec(n) -> str:
    if not isinstance(n, (int, float)) or n <= 0:
        return ""
    if n >= 10:
        return f"{round(n)} tok/s"
    return f"{n:.1f} tok/s"


def _usage_snapshot(message: dict) -> tuple:
    """Extract (input_tok, output_tok, total_tok) like the web UI usageSnapshot()."""
    meta = message.get("meta") or {}
    rm = meta.get("response_metadata") or {}
    usage = (
        meta.get("usage_metadata")
        or rm.get("usage_metadata")
        or rm.get("token_usage")
        or rm.get("usage")
        or {}
    )

    def _nested_total(key: str):
        details = usage.get(key) or {}
        return details.get("total_tokens") if isinstance(details, dict) else None

    input_tok = usage.get("prompt_tokens")
    if input_tok is None:
        input_tok = usage.get("input_tokens")
    if input_tok is None:
        input_tok = _nested_total("input_token_details")
    output_tok = usage.get("completion_tokens")
    if output_tok is None:
        output_tok = usage.get("output_tokens")
    if output_tok is None:
        output_tok = _nested_total("output_token_details")
    total_tok = usage.get("total_tokens")

    # Ollama shape lives on response_metadata, not usage_metadata.
    if input_tok is None and rm.get("prompt_eval_count") is not None:
        input_tok = rm.get("prompt_eval_count")
    if output_tok is None and rm.get("eval_count") is not None:
        output_tok = rm.get("eval_count")
    return input_tok, output_tok, total_tok


def _format_stats(message: dict, provider_name: str | None) -> str:
    """Build a one-line model/token/timing summary mirroring the web UI footer."""
    if not isinstance(message, dict):
        return ""
    meta = message.get("meta") or {}
    rm = meta.get("response_metadata") or {}
    input_tok, output_tok, total_tok = _usage_snapshot(message)
    latency_ms = message.get("latency_ms")

    # tok/s: prefer Ollama's eval_duration (ns), else wall-clock latency.
    tok_per_sec = None
    if output_tok is not None:
        eval_duration = rm.get("eval_duration")
        if isinstance(eval_duration, (int, float)) and eval_duration > 0:
            tok_per_sec = output_tok / (eval_duration / 1e9)
        elif isinstance(latency_ms, (int, float)) and latency_ms > 0:
            tok_per_sec = output_tok / (latency_ms / 1000)

    parts: list[str] = []
    head = provider_name or message.get("provider_id")
    if head:
        parts.append(str(head))
    model_id = message.get("model_id")
    if model_id:
        parts.append(str(model_id))
    if isinstance(latency_ms, (int, float)) and latency_ms:
        parts.append(f"{int(latency_ms)} ms")
    if input_tok is not None:
        parts.append(f"↑{_fmt_tokens(input_tok)}")
    if output_tok is not None:
        parts.append(f"↓{_fmt_tokens(output_tok)} tok")
    elif input_tok is None and total_tok is not None:
        parts.append(f"tok {_fmt_tokens(total_tok)}")
    if tok_per_sec is not None:
        tps = _fmt_tok_per_sec(tok_per_sec)
        if tps:
            parts.append(tps)

    iterations = meta.get("agent_iterations")
    if isinstance(iterations, int) and iterations > 0:
        parts.append(f"{iterations} iter" + ("s" if iterations != 1 else ""))
    tool_calls = meta.get("tool_calls") or []
    if isinstance(tool_calls, list) and tool_calls:
        parts.append(f"{len(tool_calls)} tool" + ("s" if len(tool_calls) != 1 else ""))

    finish = rm.get("finish_reason") or rm.get("stop_reason")
    if finish and finish not in ("stop", "end_turn"):
        parts.append(f"[{finish}]")
    return " · ".join(p for p in parts if p)


def _fetch_provider_names(client: httpx.Client, server: str) -> dict[str, str]:
    """Best-effort provider_id → display_name map; empty on any failure."""
    try:
        r = client.get(f"{server}/api/llm-providers")
        r.raise_for_status()
        providers = r.json().get("providers", [])
    except Exception:
        return {}
    names: dict[str, str] = {}
    for provider in providers:
        if isinstance(provider, dict) and provider.get("id"):
            names[provider["id"]] = provider.get("display_name") or provider["id"]
    return names


def _print_stats(message: dict, provider_names: dict[str, str]) -> None:
    if not isinstance(message, dict):
        return
    provider_name = provider_names.get(str(message.get("provider_id") or ""))
    line = _format_stats(message, provider_name)
    if line:
        print(line, file=sys.stderr)


def _health_check(client: httpx.Client, server: str) -> None:
    try:
        r = client.get(f"{server}/api/health")
        r.raise_for_status()
    except httpx.TransportError as exc:
        _die(_EXIT_TRANSPORT, f"cannot reach GCS at {server}: {exc}")
    except httpx.HTTPStatusError as exc:
        _die(_EXIT_TRANSPORT, f"GCS health check failed ({exc.response.status_code})")


def _create_session(
    client: httpx.Client,
    server: str,
    run_mode: str,
    title: str | None = None,
    provider_id: str | None = None,
) -> str:
    payload: dict = {"title": title or "CLI session", "mode": run_mode}
    if provider_id:
        payload["provider_id"] = provider_id
    try:
        r = client.post(f"{server}/api/ai/sessions", json=payload)
    except httpx.TransportError as exc:
        _die(_EXIT_TRANSPORT, f"transport error creating session: {exc}")

    if r.status_code >= 500:
        _die(_EXIT_PROVIDER, f"server error creating session ({r.status_code}) — check GCS logs")
    if r.status_code >= 400:
        _die(_EXIT_BACKEND_4XX, f"failed to create session ({r.status_code}): {r.text}")

    data = r.json()
    session_id: str = data["session"]["id"]
    print(f"session: {session_id}", file=sys.stderr)
    return session_id


def _verify_session(client: httpx.Client, server: str, session_id: str) -> None:
    try:
        r = client.get(f"{server}/api/ai/sessions/{session_id}")
    except httpx.TransportError as exc:
        _die(_EXIT_TRANSPORT, f"transport error loading session: {exc}")

    if r.status_code == 404:
        _die(_EXIT_BACKEND_4XX, f"session not found: {session_id}")
    if r.status_code >= 500:
        _die(_EXIT_PROVIDER, f"server error loading session ({r.status_code}) — check GCS logs")
    if r.status_code >= 400:
        _die(_EXIT_BACKEND_4XX, f"failed to load session ({r.status_code}): {r.text}")


def _patch_provider(client: httpx.Client, server: str, session_id: str, provider_id: str) -> None:
    try:
        r = client.patch(
            f"{server}/api/ai/sessions/{session_id}",
            json={"provider_id": provider_id},
        )
    except httpx.TransportError as exc:
        _die(_EXIT_TRANSPORT, f"transport error updating session: {exc}")

    if r.status_code == 404:
        _die(_EXIT_BACKEND_4XX, f"session not found: {session_id}")
    if r.status_code >= 500:
        _die(_EXIT_PROVIDER, f"server error updating session ({r.status_code}) — check GCS logs")
    if r.status_code >= 400:
        _die(_EXIT_BACKEND_4XX, f"failed to update session ({r.status_code}): {r.text}")

    print(f"model: {provider_id}", file=sys.stderr)


def _send_message(
    client: httpx.Client,
    server: str,
    session_id: str,
    prompt: str,
    run_mode: str,
) -> tuple[str, dict]:
    try:
        r = client.post(
            f"{server}/api/ai/sessions/{session_id}/messages",
            json={"content": prompt, "run_mode": run_mode},
        )
    except httpx.TransportError as exc:
        _die(_EXIT_TRANSPORT, f"transport error sending message: {exc}")

    if r.status_code == 404:
        _die(_EXIT_BACKEND_4XX, f"session not found: {session_id}")
    if r.status_code >= 500:
        _die(_EXIT_PROVIDER, f"server error ({r.status_code}) — check GCS logs")
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        _die(_EXIT_BACKEND_4XX, f"request error ({r.status_code}): {detail}")

    data = r.json()
    message = data.get("assistant_message", {}) or {}
    content = message.get("content", "")
    if not content:
        _die(_EXIT_PROVIDER, "empty response from assistant")
    return str(content), message


def _send_message_stream(
    client: httpx.Client,
    server: str,
    session_id: str,
    prompt: str,
    run_mode: str,
) -> tuple[str, dict]:
    url = f"{server}/api/ai/sessions/{session_id}/messages/stream"
    payload = {"content": prompt, "run_mode": run_mode}
    final_content = ""
    final_message: dict = {}
    try:
        with client.stream("POST", url, json=payload) as r:
            if r.status_code == 404:
                _die(_EXIT_BACKEND_4XX, f"session not found: {session_id}")
            if r.status_code >= 500:
                _die(_EXIT_PROVIDER, f"server error ({r.status_code})")
            if r.status_code >= 400:
                _die(_EXIT_BACKEND_4XX, f"request error ({r.status_code})")
            for line in r.iter_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    _die(_EXIT_PROVIDER, f"malformed streaming event: {line[:120]}")
                if not isinstance(event, dict):
                    _die(_EXIT_PROVIDER, f"unexpected streaming event payload: {line[:120]}")
                t = event.get("type")
                if t == "assistant_delta":
                    delta = event.get("delta")
                    if not isinstance(delta, str):
                        _die(_EXIT_PROVIDER, f"malformed assistant_delta event: {line[:120]}")
                    print(delta, end="", flush=True)
                elif t == "assistant_message":
                    msg = event.get("message", {})
                    if isinstance(msg, dict):
                        final_message = msg
                        content = msg.get("content", "")
                        if not isinstance(content, str):
                            _die(_EXIT_PROVIDER, f"malformed assistant_message event: {line[:120]}")
                        final_content = content
                    else:
                        _die(_EXIT_PROVIDER, f"malformed assistant_message event: {line[:120]}")
                elif t == "error":
                    print(flush=True)
                    _die(_EXIT_PROVIDER, f"stream error: {event.get('detail', 'unknown')}")
    except httpx.TransportError as exc:
        _die(_EXIT_TRANSPORT, f"transport error during stream: {exc}")
    print(flush=True)
    if not final_content:
        _die(_EXIT_PROVIDER, "empty response from assistant")
    return final_content, final_message


def _send_session_command(
    client: httpx.Client,
    server: str,
    session_id: str,
    command: str,
) -> str:
    try:
        r = client.post(
            f"{server}/api/ai/sessions/{session_id}/commands",
            json={"command": command},
        )
    except httpx.TransportError as exc:
        _die(_EXIT_TRANSPORT, f"transport error sending command: {exc}")

    if r.status_code == 404:
        _die(_EXIT_BACKEND_4XX, f"session not found: {session_id}")
    if r.status_code >= 500:
        _die(_EXIT_PROVIDER, f"server error ({r.status_code}) — check GCS logs")
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        _die(_EXIT_BACKEND_4XX, f"command error ({r.status_code}): {detail}")

    data = r.json()
    content = data.get("assistant_message", {}).get("content", "")
    if not content:
        _die(_EXIT_PROVIDER, "empty response from session command")
    return str(content)


def _write_output_file(path: str, content: str) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as exc:
        _die(_EXIT_TRANSPORT, f"failed to write output file {path!r}: {exc}")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gcs-ai",
        description="Send a prompt to the GCS AI backend and print the response.",
    )
    p.add_argument("prompt_pos", nargs="?", metavar="PROMPT", help="prompt text")
    p.add_argument("--prompt", metavar="TEXT", help="prompt text (alternative to positional)")
    p.add_argument(
        "--server",
        metavar="URL",
        default=None,
        help="GCS base URL (default: $GCS_AI_SERVER or http://127.0.0.1:8080)",
    )
    p.add_argument(
        "--run-mode",
        choices=["agent", "chat"],
        default="agent",
        metavar="MODE",
        help="run mode: agent (default) or chat",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        metavar="SECONDS",
        help="request timeout in seconds (default: 120)",
    )
    p.add_argument(
        "--session-id",
        metavar="ID",
        default=None,
        help="reuse an existing session instead of creating a new one",
    )
    p.add_argument(
        "--new-session",
        action="store_true",
        default=False,
        help="force creation of a new session (cannot be combined with --session-id)",
    )
    p.add_argument(
        "--title",
        metavar="TEXT",
        default=None,
        help="title for a newly created session",
    )
    p.add_argument(
        "--output-file",
        metavar="PATH",
        default=None,
        help="also write the final assistant answer to this file",
    )
    p.add_argument(
        "--provider-id",
        metavar="PROVIDER_ID",
        default=None,
        help="provider id to set when creating a new session",
    )
    p.add_argument(
        "--model",
        metavar="PROVIDER_ID",
        default=None,
        help="set the active provider for the session before sending (via PATCH)",
    )
    p.add_argument(
        "--stream",
        action="store_true",
        default=False,
        help="stream response tokens progressively via /messages/stream",
    )
    p.add_argument(
        "--no-stats",
        action="store_true",
        default=False,
        help="suppress the model/token/timing summary line printed to stderr",
    )
    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # Resolve prompt
    if args.prompt and args.prompt_pos:
        _die(_EXIT_USAGE, "specify prompt as a positional argument or --prompt, not both")
    raw_prompt: str | None = args.prompt or args.prompt_pos

    # Detect /model <provider-id> slash form
    slash_provider: str | None = None
    if raw_prompt and raw_prompt.startswith("/model"):
        parts = raw_prompt.split(None, 1)
        if len(parts) != 2 or not parts[1].strip():
            _die(_EXIT_USAGE, "/model requires a provider id: /model <provider-id>")
        slash_provider = parts[1].strip()

    # Detect session commands: /context, /tool-activity, /retrieval-surfaces,
    # /capabilities brief, /capabilities full
    session_command: str | None = None
    if raw_prompt and slash_provider is None:
        normalized_input = raw_prompt.strip().lower()
        session_command = _SESSION_COMMANDS.get(normalized_input)

    # A prompt is required unless the entire input is a /model or session command
    prompt: str | None = raw_prompt if (slash_provider is None and session_command is None) else None
    if slash_provider is None and session_command is None and not prompt:
        parser.print_usage(sys.stderr)
        _die(_EXIT_USAGE, "a prompt is required")

    # Mutual exclusions
    if args.new_session and args.session_id:
        _die(_EXIT_USAGE, "--new-session and --session-id are mutually exclusive")
    if slash_provider and args.model:
        _die(_EXIT_USAGE, "/model in prompt and --model flag are mutually exclusive")
    if args.provider_id and args.model:
        _die(_EXIT_USAGE, "--provider-id and --model are mutually exclusive")
    if args.provider_id and slash_provider:
        _die(_EXIT_USAGE, "--provider-id and /model are mutually exclusive")
    if args.provider_id and args.session_id and not args.new_session:
        _die(_EXIT_USAGE, "--provider-id only applies when creating a new session")
    if slash_provider and not args.session_id:
        _die(_EXIT_USAGE, "/model requires --session-id to identify the session to update")
    if args.title and args.session_id and not args.new_session:
        _die(_EXIT_USAGE, "--title has no effect when reusing a session via --session-id")

    server = (args.server or os.environ.get("GCS_AI_SERVER") or "http://127.0.0.1:8080").rstrip("/")
    provider_id: str | None = args.model or slash_provider

    with httpx.Client(timeout=args.timeout) as client:
        _health_check(client, server)

        if args.session_id and not args.new_session:
            session_id = args.session_id
            _verify_session(client, server, session_id)
        else:
            session_id = _create_session(
                client,
                server,
                args.run_mode,
                title=args.title,
                provider_id=args.provider_id,
            )

        if provider_id:
            _patch_provider(client, server, session_id, provider_id)

        # Pure /model command — no message to send
        if slash_provider:
            return

        if session_command:
            answer = _send_session_command(client, server, session_id, session_command)
            print(answer)
        else:
            if args.stream:
                answer, message = _send_message_stream(client, server, session_id, prompt, args.run_mode)
            else:
                answer, message = _send_message(client, server, session_id, prompt, args.run_mode)
                print(answer)
            if not args.no_stats:
                _print_stats(message, _fetch_provider_names(client, server))
        if args.output_file:
            _write_output_file(args.output_file, answer)


if __name__ == "__main__":
    main()
