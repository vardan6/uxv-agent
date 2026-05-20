# Remote Rover TTS Service

`tts_service/` is the local text-to-speech microservice used by GCS AI response playback.

Quick setup:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
python -m venv tts_service/.venv
source tts_service/.venv/bin/activate
pip install -r tts_service/requirements.txt
python tts_service/scripts/download_kokoro_models.py
```

Run:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover/tts_service
./run.sh
```

Default health URL:
- `http://127.0.0.1:9101/health`

Notes:
- current engine is `kokoro-onnx`
- model files stay local under `tts_service/models/`
- GCS points at this service through `config/common.local.json` under `ai_settings.tts`

Remote Rover will likely need several local services:

- GCS web app
- TTS service
- speech-to-text service
- RAG service
- mission/agent service
- simulator

A future root-level launcher can keep this manageable:

```text
remote-rover/
  services.yml
  tools/
    run_services.py
```

Then the full local stack could be launched with one command, while still keeping each service independently runnable for development.
