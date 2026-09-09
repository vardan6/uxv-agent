"""Characterization tests for the repository-owned RAG command surface."""

import os
from pathlib import Path
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
RAG_CLI = REPO_ROOT / "bin" / "rag"


def _executable(path: Path, contents: str) -> None:
    path.write_text(contents)
    path.chmod(0o755)


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(RAG_CLI), *args],
        cwd=REPO_ROOT,
        env={**os.environ, **(env or {})},
        text=True,
        capture_output=True,
        check=False,
    )


def test_help_lists_the_complete_canonical_command_surface() -> None:
    result = _run("help")

    assert result.returncode == 1
    for command in ("up", "down", "status", "logs", "ingest", "eval"):
        assert command in result.stdout


@pytest.mark.parametrize(
    ("command", "arguments", "expected"),
    [
        ("up", ["--remove-orphans"], ["compose", "-f", str(REPO_ROOT / "rag" / "docker-compose.yml"), "up", "-d", "--remove-orphans"]),
        ("down", ["--volumes"], ["compose", "-f", str(REPO_ROOT / "rag" / "docker-compose.yml"), "down", "--volumes"]),
        ("status", [], ["compose", "-f", str(REPO_ROOT / "rag" / "docker-compose.yml"), "ps"]),
        ("logs", ["qdrant"], ["compose", "-f", str(REPO_ROOT / "rag" / "docker-compose.yml"), "logs", "--tail=50", "-f", "qdrant"]),
    ],
)
def test_qdrant_commands_delegate_to_the_service_compose_file(tmp_path: Path, command: str, arguments: list[str], expected: list[str]) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    call_log = tmp_path / "docker-args"
    _executable(bin_dir / "docker", '#!/usr/bin/env sh\nprintf "%s\\n" "$@" > "$RAG_TEST_LOG"\n')

    result = _run(command, *arguments, env={"PATH": f"{bin_dir}:{os.environ['PATH']}", "RAG_TEST_LOG": str(call_log)})

    assert result.returncode == 0
    assert call_log.read_text().splitlines() == expected


@pytest.mark.parametrize(
    ("command", "module", "arguments"),
    [("ingest", "rag.ingest", ["--dry-run"]), ("eval", "rag.eval", ["--limit", "1"])],
)
def test_python_commands_use_the_repo_root_and_expected_module(tmp_path: Path, command: str, module: str, arguments: list[str]) -> None:
    call_log = tmp_path / "python-args"
    fake_python = tmp_path / "python"
    _executable(fake_python, '#!/usr/bin/env sh\nprintf "%s\\n" "$@" > "$RAG_TEST_LOG"\n')

    result = _run(command, *arguments, env={"RAG_PYTHON": str(fake_python), "RAG_TEST_LOG": str(call_log)})

    assert result.returncode == 0
    assert call_log.read_text().splitlines() == ["-m", module, *arguments]


def test_unknown_command_fails_with_usage() -> None:
    result = _run("unknown")

    assert result.returncode == 1
    assert "Usage: bin/rag" in result.stdout
