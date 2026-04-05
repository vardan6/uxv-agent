from __future__ import annotations

import uvicorn

from gcs_server.config import load_config


if __name__ == "__main__":
    config = load_config()
    uvicorn.run(
        "gcs_server.app:app",
        host=str(config.gcs["host"]),
        port=int(config.gcs["port"]),
        reload=False,
    )
