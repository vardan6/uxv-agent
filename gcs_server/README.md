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

Notes:
- shared runtime config lives in `../config/common.local.json`
- the GCS is the current home of dashboard, replay, AI chat, and mission-planning/execution APIs
- agent-specific local instructions remain in `AGENTS.md`
