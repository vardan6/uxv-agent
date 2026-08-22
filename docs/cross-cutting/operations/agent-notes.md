# Agent Notes

This file stores repository-local agent workflow exceptions that supplement the shared root `AGENTS.md` symlink. It covers only constraints the shared workflow cannot know ahead of time.

## Current Exceptions

- Do not create, expand, or run tests unless the user explicitly asks. Existing tests may be read for context, but testing work is out of scope by default during the current implementation stage.
- When tests *are* authorized: the `gcs_server` suite runs as `PYTHONPATH=<repo-root> .venv/bin/python -m pytest` invoked from `gcs_server/`. The shared `.venv` at the repo root has the deps (the rtk-wrapped system `python3` does not), and the repo-root path is required because modules import `from gcs_server.*` internally while the tests import bare `ai.*` / `routers.*`. In this environment the bare `pytest` binary is intercepted by an `rtk` shell hook that fails to spawn — always invoke it as `PYTHONPATH=".:.." ../.venv/bin/python -m pytest`, never bare `pytest`.

## Scope

These notes apply across this repository, including `gcs_server/`, `3d-env/`, `rover-sim-next/`, and related shared docs, unless a future note narrows the scope explicitly.
