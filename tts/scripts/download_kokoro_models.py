from __future__ import annotations

import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT_DIR / "models"
FILES = {
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}


def download(url: str, target: Path) -> None:
    if target.exists() and target.stat().st_size > 0:
        print(f"exists: {target}")
        return
    print(f"downloading: {url}")
    tmp_target = target.with_suffix(target.suffix + ".tmp")
    urllib.request.urlretrieve(url, tmp_target)
    tmp_target.replace(target)
    print(f"saved: {target}")


def main() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for filename, url in FILES.items():
        download(url, MODEL_DIR / filename)


if __name__ == "__main__":
    main()
