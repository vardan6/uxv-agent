# Remote Rover TTS Service

`tts_service/` is the local text-to-speech microservice for Remote Rover AI response playback.

It is designed to replace weak browser-only text-to-speech with a better free/open-source local voice engine while keeping everything inside the `remote-rover/` repository.

## What It Provides

- Python FastAPI service
- Kokoro ONNX engine wrapper
- OpenAI-style speech endpoint: `POST /v1/audio/speech`
- Voice list endpoint: `GET /voices`
- Health endpoint: `GET /health`
- Local model download script
- Manual run script

The GCS can call this service through its backend proxy endpoint:

```http
POST /api/ai-tts/speech
```

## Directory Layout

```text
remote-rover/
  tts_service/
    README.md
    requirements.txt
    app.py
    config.py
    engines/
      kokoro.py
    models/
      .gitkeep
    scripts/
      download_kokoro_models.py
      run.sh
```

## Engine

Current engine: `kokoro-onnx`.

Useful upstream projects:

- Kokoro-FastAPI: https://github.com/remsky/Kokoro-FastAPI
- kokoro-onnx: https://github.com/thewh1teagle/kokoro-onnx

Kokoro model files are not committed to git. Download them locally into `tts_service/models/`.

## Setup

From the repository root:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
python -m venv tts_service/.venv
source tts_service/.venv/bin/activate
pip install -r tts_service/requirements.txt
python tts_service/scripts/download_kokoro_models.py
```

The download script stores these files:

```text
tts_service/models/kokoro-v1.0.onnx
tts_service/models/voices-v1.0.bin
```

## Run

From the repository root:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
source tts_service/.venv/bin/activate
python -m uvicorn tts_service.app:app --host 127.0.0.1 --port 9101
```

Or use the helper:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover/tts_service
./scripts/run.sh
```

Health check:

```text
http://127.0.0.1:9101/health
```

A healthy service returns `ready: true` after the Kokoro model and voices files exist.

## API

Health check:

```http
GET /health
```

List voices:

```http
GET /voices
```

Generate speech:

```http
POST /v1/audio/speech
Content-Type: application/json
```

Example request:

```json
{
  "input": "Remote Rover AI response text.",
  "voice": "af_sky",
  "format": "wav",
  "speed": 1.0
}
```

Current response format:

- `audio/wav`

## Configuration

The service accepts environment variables:

```text
REMOTE_ROVER_TTS_HOST=127.0.0.1
REMOTE_ROVER_TTS_PORT=9101
REMOTE_ROVER_TTS_MODEL=/path/to/kokoro-v1.0.onnx
REMOTE_ROVER_TTS_VOICES=/path/to/voices-v1.0.bin
REMOTE_ROVER_TTS_VOICE=af_sky
REMOTE_ROVER_TTS_LANGUAGE=en-us
REMOTE_ROVER_TTS_MAX_TEXT_CHARS=6000
```

GCS shared config lives in:

```text
remote-rover/config/common.local.json
```

Relevant AI TTS settings:

```json
{
  "ai_settings": {
    "tts": {
      "enabled": true,
      "engine": "kokoro_service",
      "auto_read": false,
      "service_url": "http://127.0.0.1:9101",
      "voice": "af_sky",
      "format": "wav",
      "speed": 1.0,
      "browser_fallback": true
    }
  }
}
```

These can also be edited from the GCS Settings page under `AI Settings`.

## Running The Overall Remote Rover Project

Use separate terminals.

Terminal 1: start MQTT if it is not already running.

Terminal 2: start the GCS.

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
source gcs_server/.venv/bin/activate
python -m uvicorn gcs_server.app:app --host 127.0.0.1 --port 9002
```

Open:

```text
http://127.0.0.1:9002
```

Terminal 3: start the TTS service.

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
source tts_service/.venv/bin/activate
python -m uvicorn tts_service.app:app --host 127.0.0.1 --port 9101
```

Terminal 4: start the simulator.

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover/3d-env
source .venv/bin/activate
python simulator/main.py
```

Operational order:

1. Start MQTT.
2. Start the GCS.
3. Start the TTS service.
4. Open the GCS in a browser.
5. Start the simulator.
6. In GCS Settings, set AI Settings speech engine to `Kokoro local service`.
7. Use AI Chat and test response voice playback.

## Future Multi-Service Launcher

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
