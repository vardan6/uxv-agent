import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = REPO_ROOT / "tools" / "gcs_ai_cli.py"

spec = importlib.util.spec_from_file_location("gcs_ai_cli", CLI_PATH)
gcs_ai_cli = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(gcs_ai_cli)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self):
        self.posts = []
        self.gets = []

    def post(self, url, json):
        self.posts.append((url, json))
        return FakeResponse(payload={"session": {"id": "session-1"}})

    def get(self, url):
        self.gets.append(url)
        return FakeResponse(payload={"session": {"id": "session-1"}})


class FakeStreamResponse:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def iter_lines(self):
        return iter(self._lines)


class FakeStreamClient:
    def __init__(self, lines):
        self._lines = lines

    def stream(self, method, url, json):
        return FakeStreamResponse(self._lines)


def test_parser_accepts_provider_id_for_new_session() -> None:
    parser = gcs_ai_cli._build_parser()

    args = parser.parse_args(["--provider-id", "provider-default-ollama", "hello"])

    assert args.provider_id == "provider-default-ollama"


def test_create_session_sends_provider_id() -> None:
    client = FakeClient()

    session_id = gcs_ai_cli._create_session(
        client,
        "http://gcs.test",
        "agent",
        title="CLI",
        provider_id="provider-default-ollama",
    )

    assert session_id == "session-1"
    assert client.posts == [
        (
            "http://gcs.test/api/ai/sessions",
            {
                "title": "CLI",
                "mode": "agent",
                "provider_id": "provider-default-ollama",
            },
        )
    ]


def test_verify_session_checks_existing_session_endpoint() -> None:
    client = FakeClient()

    gcs_ai_cli._verify_session(client, "http://gcs.test", "session-1")

    assert client.gets == ["http://gcs.test/api/ai/sessions/session-1"]


def test_stream_malformed_json_exits_as_provider_error() -> None:
    client = FakeStreamClient(["not-json"])

    with pytest.raises(SystemExit) as exc:
        gcs_ai_cli._send_message_stream(
            client,
            "http://gcs.test",
            "session-1",
            "hello",
            "agent",
        )

    assert exc.value.code == gcs_ai_cli._EXIT_PROVIDER
