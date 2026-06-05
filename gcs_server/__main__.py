from __future__ import annotations

from datetime import datetime
import uvicorn

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
del _os, _sys

from gcs_server.config import load_config


if __name__ == "__main__":
    config = load_config()
    print(f"[gcs_server] Starting at {datetime.now().astimezone().isoformat()}", flush=True)
    uvicorn.run(
        "gcs_server.app:app" if __package__ else "app:app",
        host=str(config.gcs["host"]),
        port=int(config.gcs["port"]),
        reload=False,
    )
