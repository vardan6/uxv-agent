# GCS AI CLI Plan

Status date: 2026-06-16.

This document captures the implementation plan for a standalone terminal CLI
that talks to the existing GCS AI backend. It is a design-and-sequencing plan,
not an implementation status log.

## Goal

Provide a separate executable CLI that lets an operator or developer send a
prompt to the GCS AI chat system from a terminal and receive the assistant
response on standard output, without opening the browser UI.

The CLI should be thin: it should reuse the existing GCS `/api/ai/...` surface
instead of creating a second AI runtime or bypassing the current session store,
provider routing, tool registry, and trace pipeline.

## Non-goals

- Do not create a second direct-to-provider chat path inside the CLI.
- Do not duplicate AI session persistence outside the existing GCS SQLite store.
- Do not require browser code to be running.
- Do not require simulator, replay, or mission execution services for plain chat.
- Do not introduce a new long-lived daemon in v1.
- Do not redesign the current `/ai` backend APIs before proving the thin-client path.

## Current backend facts

The current GCS code already provides the core backend surfaces needed for a
terminal client:

- The AI service is instantiated inside the main FastAPI lifespan and reuses the
  existing session store, provider resolution, tool registry, and trace store.
- Session creation already exists at `POST /api/ai/sessions`.
- Blocking chat already exists at `POST /api/ai/sessions/{session_id}/messages`.
- Streaming chat already exists at
  `POST /api/ai/sessions/{session_id}/messages/stream`.
- Session lookup/listing already exists and can support later CLI affordances
  such as resume, list, archive, and retry.

Relevant code:

- `gcs_server/app.py`
- `gcs_server/routers/ai.py`
- `gcs_server/ai/chat_service.py`
- `gcs_server/ai/session_store.py`

## Minimum runtime required

### Required

- The GCS FastAPI server must be running.
- At least one LLM provider must be configured and reachable through the current
  GCS provider-routing path.
- The CLI must be able to reach the configured GCS host/port over HTTP.

### Not required for plain chat

- A browser session.
- The simulator.
- A live rover.
- A healthy MQTT broker connection.

### Important runtime nuance

Today the GCS app still boots its full runtime, including control and MQTT
startup, when the process starts. The CLI does not change that. The practical
v1 assumption is therefore:

- if the GCS process is up, the CLI can call chat
- MQTT may still be disconnected without blocking plain chat

If later operation shows that chat-only use should not boot MQTT/control at all,
that becomes a separate backend refactor and should follow the thin-client v1,
not precede it.

## CLI shape

## Placement

Place the executable outside the browser/backend package internals, as a small
repo tool. Preferred locations:

- `tools/gcs_ai_cli.py`
- or `bin/gcs-ai` as a thin launcher that calls `tools/gcs_ai_cli.py`

The file should be executable and callable directly from the terminal.

## Invocation model

The CLI should support both a positional prompt and an explicit long flag:

```bash
gcs-ai "Summarize the active mission state."
gcs-ai --prompt "Summarize the active mission state."
```

Do not use `-p` for prompt.

Reason:

- local `codex` uses `-p` for `--profile`
- local `claude` uses `-p` for `--print`

To avoid conflicting operator expectations, reserve:

- `--prompt` for the prompt text
- `--print` only if a future mode distinction requires it

In v1, plain terminal output should happen by default, so a `--print` flag is
not necessary.

## Minimum v1 flags

- `--prompt <text>`: explicit prompt text alternative to positional argument
- `--server <url>`: GCS base URL, defaulting to local config or
  `http://127.0.0.1:8080`
- `--session-id <id>`: reuse an existing AI session
- `--new-session`: force creation of a new session
- `--title <text>`: title for a newly created session
- `--stream`: use the streaming endpoint and print tokens progressively
- `--output-file <path>`: also write the final assistant text to a file
- `--provider-id <id>`: optional per-session provider selection on new session
- `--run-mode <chat|agent>`: default `chat`
- `--timeout <seconds>`: request timeout

## Defer from v1 unless implementation stays trivial

- `list-sessions`
- `resume latest`
- `retry last answer`
- `archive` / `restore` / `purge`
- slash-command wrappers for local session commands
- structured JSON output mode
- shell piping modes beyond plain stdin/stdout ergonomics

## User-visible behavior

### Default mode

For ordinary questions, the CLI should prefer `agent` mode by default.

Reason:

- it matches the richer `/ai` behavior already present in the GCS
- it preserves tool-backed grounding for questions about rover state, settings,
  replay, docs, and mission context
- it aligns the terminal path with the intended future “primary agent” direction

The CLI should still allow explicit override via:

- `--run-mode chat`
- `--run-mode agent`

### New session path

If the caller passes `--new-session` or omits `--session-id`, the CLI should:

1. check server reachability
2. create a new AI session
3. send the prompt
4. print the assistant answer
5. emit the resulting `session_id` once to stderr so the user can continue the
   conversation later

### Existing session path

If `--session-id` is provided, the CLI should:

1. verify the session exists
2. send the prompt into that session
3. print only the assistant answer to stdout
4. return a non-zero exit code on API/provider failure

### Output contract

- Standard output should contain the assistant answer only.
- Operational/status noise should go to stderr.
- `--output-file` should write the final assistant answer exactly once after the
  request completes.
- In streaming mode, stdout should show deltas as they arrive and still finish
  with a newline.

## Slash-command parity

The CLI should expose the same slash-command surface that is already useful in
the web chat, instead of inventing a separate command vocabulary for terminal
use.

### Current web-chat command inventory

#### Session-command endpoint backed

These already map to `POST /api/ai/sessions/{session_id}/commands`:

- `/capabilities brief`
- `/capabilities full`
- `/retrieval-surfaces`
- `/tool-activity`
- `/context`

#### Run-mode backed

These are not backend “session commands”; they select a different execution path:

- `/intent`
- `/plan`

### Additional CLI requirement

The CLI should also support:

- `/model`

Important current backend fact:

- `/model` is not part of the current web slash-command list
- `/model` is not supported by the current backend session-command endpoint
- the existing backend seam for model/provider selection is session mutation via
  `PATCH /api/ai/sessions/{session_id}` with `provider_id`

### CLI handling rules

#### `/capabilities brief`, `/capabilities full`, `/retrieval-surfaces`, `/tool-activity`, `/context`

Pass through to the existing backend command endpoint unchanged.

#### `/intent`

Interpret as:

- set effective run mode to `intent`
- send the remaining prompt text through the normal AI message path

#### `/plan`

Interpret as:

- use the existing planning-shell stream path rather than the normal message
  endpoint
- preserve the same semantics as the web chat planning-shell behavior

#### `/model`

Implement as a CLI-native command handler that:

1. resolves the current session
2. patches the session `provider_id`
3. prints a concise confirmation to stderr

Suggested forms:

```bash
gcs-ai --session-id <id> /model provider-default-ollama
gcs-ai --session-id <id> --model provider-default-ollama
```

The slash form is useful for parity with the web chat. The flag form is useful
for scripting. The CLI may support both while treating them as the same
operation.

## API mapping

### Connectivity check

Use:

- `GET /api/health`

Purpose:

- fail fast if the server is unavailable
- produce a clear transport error before attempting session creation

### Create session

Use:

- `POST /api/ai/sessions`

Payload fields:

- `title`
- `mode`
- `provider_id`
- optional `source_controls`

V1 should keep `source_controls` at backend defaults unless a concrete CLI need
appears.

### Blocking send

Use:

- `POST /api/ai/sessions/{session_id}/messages`

Payload fields:

- `content`
- `run_mode`
- optional `timezone_name`

The CLI should parse the JSON response and print the returned assistant message
content.

### Streaming send

Use:

- `POST /api/ai/sessions/{session_id}/messages/stream`

The endpoint returns NDJSON event lines. The CLI should support at least:

- `assistant_delta`
- `assistant_message`
- terminal error propagation when the HTTP response is non-200

The final persisted assistant message should be treated as the source of truth
for any `--output-file` write.

## Error handling

The CLI should distinguish these failure classes:

- transport failure: GCS unreachable, timeout, DNS, refused connection
- HTTP 404: missing session or missing in-progress stream
- HTTP 400: bad payload, unsupported run mode, invalid arguments
- HTTP 401/403: future auth failure if auth is later added
- provider failure surfaced by backend: missing model, auth failure, rate limit,
  provider timeout, invalid provider config
- malformed streaming event or unexpected payload shape

Suggested exit-code buckets:

- `1`: transport/runtime failure
- `2`: CLI usage/argument error
- `3`: backend 4xx functional error
- `4`: backend/provider execution failure

Exact numeric values are less important than documenting them and keeping them
stable once published.

## Dependencies

Preferred v1 approach:

- use Python stdlib plus one small HTTP dependency only if it clearly reduces
  complexity

Options:

- stdlib `urllib.request` / `http.client`: no new dependency, more manual code
- `requests`: simplest blocking HTTP path
- `httpx`: cleaner if both blocking and streaming ergonomics are desired

Recommendation:

- use `httpx`

Reason:

- straightforward timeout handling
- simple streaming iteration
- keeps code concise

If `httpx` is added, it must be added to the shared GCS requirements path used
by the repo venv.

### More detail: `httpx` vs dependency-minimal

This tradeoff is mainly about where complexity lives.

#### Option A: dependency-minimal

Use:

- stdlib only, or
- `requests` for blocking mode and manual handling for streaming

Pros:

- fewer added dependencies
- lower packaging churn
- easiest answer if the repo wants to stay conservative about Python libraries

Cons:

- more hand-written code for timeouts, retries, error shaping, and streaming
- rougher NDJSON handling for `/messages/stream`
- more branching if blocking and streaming use different client paths
- becomes less attractive once slash-command routing and planning-shell support
  are added

Best fit:

- if Slice 1 is intentionally blocking-only and the repo strongly prefers to
  avoid adding any dependency

#### Option B: `httpx`

Use one client library for:

- blocking JSON calls
- streamed NDJSON responses
- shared timeout and base-URL handling

Pros:

- one consistent API for both blocking and streaming
- cleaner streaming flow for `/messages/stream` and later planning-shell streams
- simpler timeout configuration
- easier future extension if auth headers, retries, or async variants are ever
  needed
- keeps the CLI logic shorter, which matters because this tool will already
  contain argument parsing, command routing, output control, and slash handling

Cons:

- one additional dependency in the repo environment
- slightly larger installation surface

Best fit:

- if the CLI is expected to support streaming, slash-command parity, and `/plan`
  early

### Recommendation after your requirements

Given the current requirements:

- prefer `agent` mode
- support slash-command parity with the web chat
- support `/model`
- support streamed terminal output

the balance shifts toward `httpx`.

Reason:

Once the CLI needs more than a single blocking POST, dependency-minimal stops
being a meaningful simplification. The complexity moves from installation to our
own code. `httpx` is the cleaner engineering choice if we intend to support the
real chat surface rather than a one-shot prompt client.

### Final recommendation

- If Slice 1 is kept strictly to blocking prompt/response only, either stdlib or
  `httpx` is acceptable.
- If we intend to move quickly into slash parity and streaming, choose `httpx`
  from the start and do not split the implementation across multiple HTTP
  stacks.

## Config behavior

V1 should keep configuration simple and explicit.

Resolution order for server URL:

1. `--server`
2. environment variable such as `GCS_AI_SERVER`
3. default `http://127.0.0.1:8080`

The CLI should not parse or mutate the shared JSON config in v1 unless there is
an explicit requirement to keep the CLI coupled to the current GCS host/port
settings file.

## Packaging and executable behavior

The CLI should be runnable in at least one of these forms:

```bash
PYTHONPATH=. .venv/bin/python tools/gcs_ai_cli.py --prompt "hello"
./bin/gcs-ai --prompt "hello"
```

Preferred end state:

- a stable launcher path in `bin/`
- implementation in `tools/`

This keeps the user-facing command short while keeping the Python logic in a
normal source file.

## Testing plan

### Unit tests

- argument parsing for positional prompt vs `--prompt`
- rejection of conflicting or missing prompt inputs
- output routing: stdout vs stderr behavior
- response parsing for blocking JSON result
- streaming NDJSON event parsing for `assistant_delta` and final
  `assistant_message`

### Integration tests

Mocked HTTP tests should cover:

- health-check failure
- create-session then send-message success
- existing-session success
- backend 400/404/provider error propagation
- streaming completion and file output

### Manual verification

Minimum smoke path:

1. start GCS
2. ensure one provider is configured and reachable
3. run blocking CLI call against a new session
4. run streaming CLI call against a new session
5. continue the same session with `--session-id`
6. verify response appears in stdout
7. verify optional `--output-file` content matches the final assistant message

## Thin-slice implementation sequence

## Slice 1 — blocking terminal chat end to end

Deliverable:

- standalone executable CLI
- health check
- new session creation
- blocking message send
- default `agent` mode
- assistant answer printed to stdout
- session id printed once on stderr for newly created sessions

Verifiable:

- one prompt can be sent from the terminal to a running GCS and the answer is
  printed

## Slice 2 — session reuse and file output

Deliverable:

- `--session-id`
- `--new-session`
- `--title`
- `--output-file`
- `/model` and `--model` provider-selection path via session patch

Verifiable:

- user can continue an earlier session and optionally save the answer to disk

## Slice 3 — streaming output

Deliverable:

- `--stream`
- NDJSON event parsing
- stable handling of partial deltas and final persisted message
- slash-command routing for `/intent` and endpoint-backed session commands

Verifiable:

- response streams progressively to the terminal and matches the persisted final
  answer

## Slice 4 — polish and operator ergonomics

Deliverable:

- cleaner stderr diagnostics
- documented exit codes
- README usage section
- complete web-chat slash parity, including `/plan`, if not already landed in
  Slice 3
- optional session listing/retry only if still small

Verifiable:

- common failures are understandable without reading backend logs

## Optional follow-on: chat-only backend mode

This is explicitly out of v1 scope.

If later needed, add a backend startup mode that skips MQTT/control/runtime
surfaces when the process is launched only to serve AI CLI traffic. That work
should be justified by real friction, not assumed up front.

## Resolved decisions

- For ordinary questions, prefer `agent` mode.
- Print a newly created session id once at session start; do not repeat it.
- CLI parity should cover the slash commands already available in the web chat.
- Add `/model` support to change the active session provider from the CLI.

## Open questions

- Should the CLI gain subcommands (`send`, `sessions list`, `retry`) early, or
  stay as a single-command interface until usage pressure appears?
- Should `/model` accept only provider ids, or also fuzzy display-name matches?
- Whether to standardize on `httpx` immediately in Slice 1, or allow a
  dependency-minimal Slice 1 and switch before streaming lands.

## Risks

- The current backend boot path still starts MQTT/control services even for
  chat-only usage, so “CLI only” still depends on the full GCS process startup
  succeeding.
- Provider failures will surface through the backend and may look opaque unless
  the CLI preserves useful error messages.
- Streaming semantics depend on the current NDJSON event contract; frontend-only
  assumptions must not leak into the CLI parser.
- `/model` uses session `provider_id` semantics, not an arbitrary raw model
  string, so CLI wording must avoid implying direct provider bypass.
- Future auth would require adding headers/token handling to the CLI contract.

## Recommendation

Implement the CLI as a thin HTTP client first. Do not refactor the backend into
a separate AI service before the CLI exists and proves the real gaps.
