"""TA6 — MAVSDK gRPC seam lifecycle and failure surfacing.

`GrpcServer` owns a real `grpc.aio` server on a background thread. These
tests avoid starting an actual server: they exercise the pieces that don't
need one (`address`, initial `running`/`error` state) and simulate the
"proto/grpc load failure" path that `_run` is explicitly written to catch,
without requiring grpcio to be absent from the test environment.
"""

from __future__ import annotations

import threading

import grpc_service


def test_address_reflects_config():
    server = grpc_service.GrpcServer()
    assert server.address == f"{grpc_service.config.MAVSDK_GRPC_HOST}:{grpc_service.config.MAVSDK_GRPC_PORT}"


def test_initial_state_is_not_running_and_has_no_error():
    server = grpc_service.GrpcServer()
    assert server.running is False
    assert server.error is None


def test_run_catches_import_failure_and_records_it_as_error(monkeypatch):
    """Simulates grpcio (or the generated proto stubs) being unavailable —
    the exact dependency-degradation path `_run`'s try/except targets."""
    server = grpc_service.GrpcServer()

    real_import = __import__

    def _fake_import(name, *args, **kwargs):
        if name in ("grpc", "mav_sim_pb2", "mav_sim_pb2_grpc"):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import)

    server._run()

    assert server.error is not None
    assert "grpc unavailable" in server.error
    assert server.running is False


def test_stop_without_start_does_not_raise():
    server = grpc_service.GrpcServer()
    server.stop()  # no thread/server ever created — must be a safe no-op
    assert server.running is False


def test_start_is_idempotent_and_spawns_exactly_one_thread(monkeypatch):
    server = grpc_service.GrpcServer()
    started = threading.Event()

    def _fake_run(self) -> None:
        started.set()

    monkeypatch.setattr(grpc_service.GrpcServer, "_run", _fake_run)

    server.start()
    first_thread = server._thread
    server.start()  # second call must be a no-op while a thread exists

    started.wait(timeout=2.0)
    assert server._thread is first_thread
