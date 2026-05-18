#!/usr/bin/env bash


# virtualenv .venv
source .venv/bin/activate

# pip install -r requirements-gcs.txt

printf '[gcs_server] Starting at %s\n' "$(date -Iseconds)"

python ./app.py
