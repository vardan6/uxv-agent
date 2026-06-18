# Remote Rover GCS

`gcs_server/` is the browser-facing Ground Control Station.

Use these docs first:
- `../docs/components/gcs/README.md`
- `../docs/components/gcs/design.md`
- `../docs/components/gcs/internals/api-and-runtime.md`
- `../docs/cross-cutting/operations/run-and-config.md`

Quick start:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
pip install -r gcs_server/requirements-gcs.txt
python -m gcs_server
```

Alternative local run:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover/gcs_server
./run.sh
```

Default URL:
- `http://127.0.0.1:8080` from `config/common.example.json` by default

AI CLI:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
./bin/gcs-ai "Summarize the active mission state."
./bin/gcs-ai --stream --prompt "What can you see in current rover context?"
./bin/gcs-ai --session-id <session-id> "Continue from the previous answer."
./bin/gcs-ai --provider-id <provider-id> --title "CLI session" "Hello"
./bin/gcs-ai --session-id <session-id> --model <provider-id>
```

`stdout` contains only the assistant answer. Session ids, diagnostics, and the
model/token/timing stats line go to `stderr`; pass `--no-stats` to suppress the
stats line. Set `GCS_AI_SERVER` or pass `--server` to target a non-default GCS
URL.

Notes:
- shared runtime config lives in `../config/common.local.json`
- the GCS is the current home of dashboard, replay, AI chat, and mission-planning/execution APIs
- agent-specific local instructions remain in `AGENTS.md`
