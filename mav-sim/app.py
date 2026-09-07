import asyncio
import queue
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

import config
import mavlink_listener
from transport_manager import TransportManager

app = FastAPI()
transport_manager = TransportManager()

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/mission")
async def api_mission():
    return mavlink_listener.get_mission()


@app.get("/api/transports")
async def api_transports():
    return transport_manager.snapshot()


@app.post("/api/simulate")
async def api_simulate(interval: float = 2.0):
    asyncio.create_task(mavlink_listener.simulate_execution(manager.broadcast, interval))
    return {"status": "started", "interval": interval}


class _ConnectionManager:
    def __init__(self):
        self._clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._clients.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self._clients:
            self._clients.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in self._clients:
                self._clients.remove(ws)


manager = _ConnectionManager()


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def _drain():
    q = mavlink_listener.get_queue()
    while True:
        try:
            entry = await asyncio.to_thread(q.get, True, 0.1)
            await manager.broadcast(entry)
        except queue.Empty:
            pass


@app.on_event("startup")
async def _startup():
    transport_manager.start()
    mavlink_listener.start()
    asyncio.create_task(_drain())


@app.on_event("shutdown")
async def _shutdown():
    transport_manager.stop()


if __name__ == "__main__":
    uvicorn.run(app, host=config.WEB_HOST, port=config.WEB_PORT)
