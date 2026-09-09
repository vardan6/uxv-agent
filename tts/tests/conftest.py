from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tts import app as app_module

from fakes import FakeTTSEngine


@pytest.fixture
def fake_engine(monkeypatch: pytest.MonkeyPatch) -> FakeTTSEngine:
    """Swap the module-level `engine` singleton for a fake, per test.

    `app.py` builds `engine = KokoroEngine(...)` once at import time and every
    route closes over that module attribute. Monkeypatching the attribute
    (rather than constructing a second `FastAPI` app) exercises the real
    routes exactly as they run in production, with no model files or
    inference involved.
    """
    engine = FakeTTSEngine()
    monkeypatch.setattr(app_module, "engine", engine)
    return engine


@pytest.fixture
def client(fake_engine: FakeTTSEngine) -> TestClient:
    return TestClient(app_module.app)
