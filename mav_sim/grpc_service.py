"""Minimal real gRPC server for the mav_sim MAVSDK seam.

This is a small, self-contained service (see proto/mav_sim.proto) — not the
official MAVSDK plugin proto set. It exists so the MAVSDK gRPC transport reports
an actually-running server and a client can connect, read sim state, and stream
telemetry, without dragging in the full C++ mavsdk_server.

grpc is imported lazily so the base monitor app keeps running when grpcio is not
installed and the transport is left disabled.
"""

from __future__ import annotations

import asyncio
import threading

import config
import mavlink_listener

SIM_VERSION = "0.5.0"


def _build_servicer(grpc, pb2, pb2_grpc):
    class MavSimServicer(pb2_grpc.MavSimServicer):
        async def GetInfo(self, request, context):
            return pb2.InfoResponse(
                vehicle="mav_sim",
                version=SIM_VERSION,
                dialect=config.MAVLINK_DIALECT,
                system_id=1,
            )

        async def GetMission(self, request, context):
            mission = mavlink_listener.get_mission()
            items = [
                pb2.MissionItem(
                    seq=int(item.get("seq", 0)),
                    command=int(item.get("command", 0)),
                    latitude=float(item.get("_lat", 0.0)),
                    longitude=float(item.get("_lon", 0.0)),
                    altitude=float(item.get("_alt", 0.0)),
                )
                for item in mission["items"]
            ]
            return pb2.MissionResponse(count=mission["count"], items=items)

        async def SubscribeTelemetry(self, request, context):
            interval = request.interval_seconds or 2.0
            mission = mavlink_listener.get_mission()
            for item in mission["items"]:
                yield pb2.PositionUpdate(
                    seq=int(item.get("seq", 0)),
                    latitude=float(item.get("_lat", 0.0)),
                    longitude=float(item.get("_lon", 0.0)),
                    altitude=float(item.get("_alt", 0.0)),
                    reached=True,
                )
                await asyncio.sleep(interval)

    return MavSimServicer()


class GrpcServer:
    """Owns a grpc.aio server running on its own asyncio loop in a daemon thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server = None
        self._error: str | None = None
        self._stopped = False

    @property
    def address(self) -> str:
        return f"{config.MAVSDK_GRPC_HOST}:{config.MAVSDK_GRPC_PORT}"

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._error = None
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="mav-sim-grpc"
            )
            self._thread.start()

    def _run(self) -> None:
        try:
            import grpc
            import mav_sim_pb2 as pb2
            import mav_sim_pb2_grpc as pb2_grpc
        except Exception as exc:  # ImportError or proto load failure
            self._error = f"grpc unavailable: {exc}"
            return

        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve(grpc, pb2, pb2_grpc))
        except Exception as exc:  # noqa: BLE001 - surfaced via status()
            self._error = str(exc)
        finally:
            loop.close()

    async def _serve(self, grpc, pb2, pb2_grpc) -> None:
        server = grpc.aio.server()
        pb2_grpc.add_MavSimServicer_to_server(
            _build_servicer(grpc, pb2, pb2_grpc), server
        )
        server.add_insecure_port(self.address)
        self._server = server
        await server.start()
        await server.wait_for_termination()

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            loop = self._loop
            server = self._server
        if loop is not None and server is not None:
            future = asyncio.run_coroutine_threadsafe(server.stop(0), loop)
            try:
                future.result(timeout=2.0)
            except Exception:
                pass

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def running(self) -> bool:
        return (
            not self._stopped
            and self._thread is not None
            and self._thread.is_alive()
            and self._error is None
        )
