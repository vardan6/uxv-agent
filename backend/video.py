from __future__ import annotations

import base64
import json
from typing import Any


JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
WEBP_MAGIC = b"RIFF"


def _guess_mime(payload: bytes) -> str:
    if payload.startswith(JPEG_MAGIC):
        return "image/jpeg"
    if payload.startswith(PNG_MAGIC):
        return "image/png"
    if payload.startswith(WEBP_MAGIC) and payload[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def decode_mqtt_frame(payload: bytes) -> dict[str, Any]:
    try:
        decoded = json.loads(payload.decode("utf-8"))
        if isinstance(decoded, dict):
            image_b64 = decoded.get("image_b64") or decoded.get("data") or decoded.get("frame")
            mime_type = decoded.get("mime_type") or decoded.get("mimeType") or "image/jpeg"
            if image_b64:
                return {
                    "mime_type": mime_type,
                    "data": image_b64,
                }
    except Exception:
        pass

    return {
        "mime_type": _guess_mime(payload),
        "data": base64.b64encode(payload).decode("ascii"),
    }
