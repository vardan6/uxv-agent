# Claude Code Error Analysis

Scanned Claude Code transcript store under `~/.claude/projects` recursively.

- Session files scanned: `321`
- Error events found: `734`
- Sessions with at least one error: `211`

Most errors came from these workspaces:

- `remote-rover-gcs-server`: `630`
- `remote-rover`: `74`
- everything else combined: `30`

## Consolidated Table

`Token usage` is a proxy from the transcript: assistant output tokens attached to failed tool calls. It is useful for ranking waste, but it is not exact billed waste.

| Error type | Count | Typical example | Why it happens | Why it can look false/noisy | Token usage proxy | Quality impact | Can be solved? | What you can do from your side | What solving it gives |
|---|---:|---|---|---|---:|---|---|---|---|
| `command_execution_failure` | 290 | `Exit code 1`, `python: command not found`, traceback, bad cwd | Environment mismatch, wrong working dir, missing binaries, app/test/runtime failures | Some are expected during exploration or verification, but they still force retries | `234,388` | Medium to High | Mostly yes | Keep repo entrypoint stable, ensure `python`/venv/tooling paths are consistent, expose canonical run/test commands in docs or hooks | Fewer failed verification loops, better confidence, less retry churn |
| `missing_file_path` | 153 | `ENOENT ... /remote-rover/roadmap.md` | Stale path assumptions after repo/workflow moves | Very often "false" in the sense that the file exists now, but the tool tried the wrong path, wrong root, wrong case, or wrong moment | `176,698` | High | Yes | Keep canonical file locations stable, add compatibility stubs or symlinks when moving files, make root-path guidance explicit, avoid mixed roots like `remote-rover` vs `gcs_server` assumptions | Large drop in wasted turns, much better session continuity and doc-update reliability |
| `parallel_cancelled_after_peer_failure` | 82 | parallel Bash batch canceled after one sibling failed | One failure in a parallel batch fan-outs into sibling cancellations | This is mostly noise, not a real root cause | `1,581,812` | Low to Medium | Indirectly | Reduce root-cause failures above; avoid fragile commands in parallel batches; keep common commands simple and robust | Biggest token reduction multiplier because it removes secondary cancellations |
| `write_conflict_file_changed` | 75 | `File has been modified since read` | File changed after read, often by user, formatter, linter, or another agent step | Often false from your perspective because the file is "there"; the problem is freshness, not existence | `74,271` | Medium | Mostly yes | Reduce auto-formatters during active agent edits, avoid concurrent editing of same file, prefer smaller atomic edits, let agent re-read before write | Fewer write retries, fewer stale-edit loops, safer edits |
| `write_without_read` | 67 | `File has not been read yet` | Tool contract requires explicit read before write | Can feel bureaucratic or noisy, but it is a real harness rule | `148,579` | Medium | Yes | Make agent workflow stricter: always read target first, especially docs and config files | Cleaner edit flow, fewer immediate tool rejections |
| `edit_search_mismatch` | 21 | `String to replace not found` | Exact-match edit target drifted after file changed or match was too brittle | Often happens when the intended section still exists semantically but not textually | `101,374` | Medium | Mostly yes | Favor smaller edits, stable anchors, less churn in frequently edited docs, avoid manual edits mid-agent-run on same file | Less brittle patching, fewer retries, higher edit success rate |
| `user_rejected_tool` | 14 | tool use rejected by user or harness | Explicit rejection or approval boundary | This is real but not a Claude quality problem | `29,557` | Low | N/A or policy choice | Only relevant if you want fewer prompts or rejections; tune permissions or workflow expectations | Slightly smoother flow, minor token savings |
| `tool_input_validation_error` | 8 | invalid tool args, bad tool schema input | Malformed tool call | Usually genuine tool-use error, not noise | `5,690` | Low to Medium | Yes | Use simpler tool flows, avoid edge-case commands, stabilize wrappers and hooks | Small reliability improvement |
| `tool_not_available_in_context` | 7 | `No such tool available: TodoWrite` | Model expected a tool that was not enabled in that session or context | Feels false because the tool exists somewhere, just not in that run | `83,315` | Low to Medium | Partly | Keep tool availability more consistent across sessions, reduce mode and context variance | Fewer dead-end turns and fewer context-recovery steps |
| `file_too_large_for_read` | 6 | file exceeds token or tool limit | Whole-file read on large file | Real limit, but avoidable | `1,131` | Low | Yes | Keep large docs split; encourage narrow reads and search-first workflow | Small token savings, better targeted inspection |
| `path_is_directory` | 4 | `EISDIR` reading directory as file | Wrong path classification | Usually real, low severity | `907` | Low | Yes | Keep docs and file layout clearer; avoid ambiguous names | Minor reliability improvement |
| `hook_output_invalid` | 3 | hook JSON validation failed | Bug in custom hook output or schema | Real harness issue | minimal direct tool token impact | Medium | Yes | Fix hook contract or schema, validate hook output locally | Removes confusing harness-layer failures |
| `blocked_long_running_command` | 1 | blocked `sleep 90 ...` poll command | Harness refused long-running pattern | Real policy or tooling behavior | `1,110` | Low | Partly | Prefer shorter polls or background or status-friendly scripts | Minor flow improvement |

## Key Points

The two most actionable root-cause buckets are:

1. `missing_file_path`
2. `command_execution_failure`

Those are the main sources of real failure. `parallel_cancelled_after_peer_failure` is mostly secondary noise caused by root failures upstream.

The "file exists but error says no such file" cases are usually one of these:

- wrong repo root at that moment
- stale absolute path from before a move
- path case mismatch
- tool looked before the file was recreated or after it was moved
- the harness or tool expected a file but was given a directory or a path relative to a different cwd

So those failures can feel false because the file exists in the repo now, but the failure is still operationally real because the tool invocation used the wrong path at that time.

## Command Failure Breakdown

Inside the `290` `command_execution_failure` events, the common subtypes were:

- generic `exit 1`: `97`
- runtime Python tracebacks: `53`
- generic `exit 2`: `42`
- `python` missing from `PATH`: `31`
- browser or process interrupted (`exit 144`): `12`
- referenced file missing: `11`
- HTTP endpoint unreachable: `9`
- wrong working directory (`cd gcs_server` from wrong place): `8`
- `rtk find` misuse: `7`
- wrong `.venv` path: `7`
- `sqlite3` missing: `4`
- `git add` failed: `4`
- `pytest` missing: `3`

## Missing Path Breakdown

The most common missing-path targets were:

- `/mnt/c/Users/vardana/Documents/Proj/remote-rover/roadmap.md`: `48`
- `/mnt/c/Users/vardana/Documents/Proj/remote-rover/activeContext.md`: `47`
- `/mnt/c/Users/vardana/Documents/Proj/remote-rover/progress.md`: `18`
- `/mnt/c/Users/vardana/Documents/Proj/remote-rover/gcs_server/app.py`: `10`

This strongly suggests path and root mismatch after workflow or repository restructuring.

## Retry Signal

The transcript shows these failures often caused immediate retry behavior:

- `command_execution_failure`: `264` retries soon after
- `missing_file_path`: `56` retries soon after
- `write_conflict_file_changed`: `48` retries soon after

That is the strongest evidence that these failures drive extra agentic iterations, re-execution, and context growth.

## Quality Impact Summary

Highest quality-risk categories:

- `missing_file_path`
  - docs or state updates fail or are delayed
  - handoff quality, roadmap accuracy, and session continuity degrade
- `command_execution_failure`
  - model may continue after partial inspection or failed verification
  - especially risky during tests, runtime checks, or repository inspection
- `write_conflict_file_changed` and `edit_search_mismatch`
  - intended edits do not land, or the agent must re-read and re-plan
  - raises the chance of stale assumptions within a turn

`parallel_cancelled_after_peer_failure` is mostly a cost and noise amplifier rather than a primary quality problem.

## Token and Cost Impact Summary

Two useful ways to think about cost:

1. Hard lower bound

- `734` failed tool results means at least `734` extra tool-failure loops
- excluding non-root noise:
  - `82` were collateral parallel cancellations
  - `14` were user rejections
  - about `638` remain as primary system or tooling failures

2. Transcript proxy

- Assistant messages that issued failed tools account for substantial output-token volume.
- This is not exact waste because a single assistant message may contain useful reasoning plus the failing tool call.
- The largest token bucket is `parallel_cancelled_after_peer_failure`, but that overstates root waste because many of those are secondary cancellations after one upstream failure.

## Recommended Priorities

1. Stabilize canonical workflow file locations

- `activeContext.md`, `roadmap.md`, and `progress.md` caused a large share of path failures
- if they must move, keep compatibility stubs or symlinks for a transition period

2. Make environment assumptions explicit and stable

- one canonical way to run Python, tests, app servers, and scripts removes many `command_execution_failure` cases

3. Avoid concurrent edits on the same file

- this should reduce both `write_conflict_file_changed` and `edit_search_mismatch`

4. Reduce fragile parallel command batches

- this does not fix the root cause, but it reduces the cancellation multiplier and token waste

## Bottom Line

The main root causes are:

- stale file paths after repository or workflow restructuring
- environment assumptions such as `python`, `.venv`, cwd, and missing CLI tools
- brittle edit workflows: write-before-read, exact-match edits, stale-read writes
- parallel batching that multiplies one failure into several canceled calls

The main value of fixing them is:

- fewer extra ReAct iterations
- fewer retries after failed reads or writes
- more reliable doc updates and handoffs
- better verification quality
- lower transcript growth and token waste
- less false impression that the agent is flailing
