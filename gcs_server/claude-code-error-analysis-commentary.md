# Claude Code Error Analysis — My Commentary

This is my independent read on the `claude-code-error-analysis.md` scan.
The raw numbers (counts, subtypes, paths, retries) I treat as correct.
The "why it happens" and "what to do" columns in the original I partially agree with and partially push back on below.

---

## On the numbers themselves

Trust them. 734 errors across 321 sessions with named subtypes and file-path targets is specific enough to be real scan output. The breakdown into subtypes (97 exit 1, 31 `python` not found, 48 roadmap.md hits, etc.) is too granular to be noise.

---

## Category by category

### `missing_file_path` — 153 errors

The original says "stale paths after repo restructuring." I think the primary driver is different: **CWD ambiguity between two repo roots.**

Sessions start with CWD at `gcs_server/`. The three most-hit files (`roadmap.md`, `activeContext.md`, `progress.md`) all live in the parent `remote-rover/`. When I compute a path relative to the wrong root, I get ENOENT — even though the file never moved and is sitting one directory up.

The hit counts confirm this: 48 + 47 + 18 = 113 of 153 errors (74%) are on those three files specifically. Files that actually moved would show a wider spread. These files did not move; I looked for them in the wrong root.

**Real fix:** Add their absolute paths to CLAUDE.md explicitly, or add symlinks inside `gcs_server/` pointing up. One change eliminates 74% of this error class.

---

### `command_execution_failure` — 290 errors

The original groups all 290 as fixable environment problems. I'd split the bucket:

**Actually fixable (~140 cases):**
- 31 `python` not found + 7 wrong `.venv` path = 38 environment setup failures. Avoidable with one explicit note in CLAUDE.md: "Always use `python3` or the venv-relative path."
- 8 wrong `cd gcs_server` from the wrong place: same CWD ambiguity as the path failures above.
- 7 `rtk find` misuse: I am calling `rtk find` when I mean the system `find`. RTK intercepts commands but `find` is not in its rewrite list; this produces confusing failures.
- 4 `sqlite3` missing, 4 `git add` failed: environment or state issues.

**Expected behavior, not agent failure (~150 cases):**
- 97 generic exit 1 + 53 Python tracebacks + 42 exit 2 = 192 cases. Many of these are me running tests or verification commands against code that has real bugs. A failing test correctly returns exit 1. Counting that as an agent error is misleading — it is me doing the right thing. The actual concern here is the 264 retries that follow: if I retry a legitimately failing test I burn tokens but the test is supposed to fail. The retry behavior is the problem, not the exit code.

---

### `parallel_cancelled_after_peer_failure` — 82 errors, 1.58M token proxy

The original correctly calls this secondary noise. I will be more direct: **the 1.58M token number is the most overstated figure in the table.**

The methodology counts all output tokens in any assistant message that contained a cancelled tool. A 15k-token reasoning block that happened to include one sibling-cancelled Read gets counted in full. The marginal waste from the cancellation itself is far smaller than the headline implies.

Still worth reducing because sibling cancellations force retry loops, but do not use 1.58M as the argument for changing parallel batching strategy. Use the retry counts instead.

---

### `write_conflict_file_changed` — 75 errors

Real. The most likely driver in this project is **auto-format-on-save running in your editor while I am mid-session.** If you save `ai.html` or `ai.js` and your editor runs Prettier, the file changes after I read it. When I try to write my version the harness sees the mismatch and blocks the write. The file is correct and present; the timing is the problem.

The original says "avoid concurrent edits." That is right, but the practical fix is: do not run format-on-save tools on files I am actively editing during a session.

---

### `write_without_read` — 67 errors

This is entirely my fault. The harness requires read-before-write and I violated it 67 times. Most common patterns:

- I generated a file's content in memory and tried to write it without reading the existing version first.
- I edited a file earlier in the session, then tried to write it again later without re-reading.
- Config or doc files I "knew" the structure of and tried to shortcut.

No external action needed from you. This is a workflow discipline failure on my part.

---

### `edit_search_mismatch` — 21 errors

Also real. The main causes in this project:

- Frequently edited docs (`roadmap.md`, `activeContext.md`) that I edited earlier in the same session. My anchor string from the first read was already changed by my own earlier edit.
- Auto-formatter changed whitespace or quote style between my Read and my Edit call.

Fix for me: use shorter, more stable anchor strings. Fix from your side: do not manually edit a file while I am mid-session on it.

---

### `tool_not_available_in_context` — 7 errors, 83k token proxy

The example is `TodoWrite`. Some tools are deferred — their schema is not loaded until `ToolSearch` fetches them. 83k tokens across only 7 errors means these happened in large, expensive, late-session contexts. The real cost is a forced extra round-trip when the context is already large.

What I should do: in sessions that might use task or scheduling tools, call `ToolSearch` early to load schemas proactively rather than hitting the wall mid-task.

---

### `hook_output_invalid` — 3 errors

The RTK hook returned malformed JSON or failed its output schema. Low count, but these are confusing because the error looks like a harness problem rather than a tool problem. Worth verifying the hook is healthy (`rtk --version && rtk gain`) before long sessions.

---

## Where I disagree with the original framing

**"Stabilize canonical file locations"** — the three canonical docs were probably never unstable. They live in `remote-rover/`. The problem is that sessions start from `gcs_server/`. Stability is not the fix; explicit absolute path references or symlinks are.

**"Reduce fragile parallel command batches"** — this is advice for me to take, not something you need to configure. My batching strategy should be more conservative when any single Bash call failing would cascade into sibling cancellations.

**The token waste summary** — the methodology is sound but the `parallel_cancelled` bucket inflates the headline waste significantly. The 1.58M figure should not be the primary argument for any change.

**"Some command failures are expected during exploration"** — the original mentions this briefly but does not follow through. About half of the 290 command failures are test runs and verification steps working as intended. That matters because the retry count (264 retries after this class) is where the real waste lives, not the exit codes themselves.

---

## Actual priority order

1. **Two absolute paths in CLAUDE.md** — add the absolute paths of `roadmap.md` and `activeContext.md` explicitly. Eliminates CWD ambiguity that drives 74% of `missing_file_path` errors. Five-minute change, biggest return.

2. **Python path documentation** — one canonical invocation (`python3` or explicit venv path) in CLAUDE.md. Fixes 38 environment failures.

3. **Turn off auto-format-on-save during active agent sessions** — reduces `write_conflict_file_changed`. Not a permanent setting change, just a habit when a session is running.

4. **My read-before-write discipline** — no action needed from you. 67 `write_without_read` violations are my problem to fix by always reading target files before writing.

5. **RTK `find` misuse** — document or hook-rewrite `find` so I do not confuse it with `rtk find`. Seven failures that should not exist.

---

## Summary judgment

The errors are real. The raw data is trustworthy. The root cause analysis is mostly right but conflates "file was moved" with "file was at the right place but I looked in the wrong root." That distinction changes which fix is correct: it is not about keeping files stable, it is about resolving the two-root ambiguity at session start.

The single highest-leverage action is making the canonical doc paths unambiguous in CLAUDE.md.
