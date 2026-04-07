from __future__ import annotations

import uvicorn

try:
    from gcs_server.config import load_config
except ModuleNotFoundError:
    from config import load_config


if __name__ == "__main__":
    config = load_config()
    uvicorn.run(
        "gcs_server.app:app" if __package__ else "app:app",
        host=str(config.gcs["host"]),
        port=int(config.gcs["port"]),
        reload=False,
    )
