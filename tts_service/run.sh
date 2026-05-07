#!/usr/bin/env bash

echo running $0

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/download_kokoro_models.py

# cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
# source tts_service/.venv/bin/activate
# python -m uvicorn tts_service.app:app --host 127.0.0.1 --port 9101
