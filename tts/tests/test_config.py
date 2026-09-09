from __future__ import annotations

from pathlib import Path

from config import DEFAULT_MODEL_PATH, DEFAULT_VOICES_PATH, load_config


def _clear_tts_env(monkeypatch) -> None:
    for name in (
        "UXV_TTS_HOST",
        "UXV_TTS_PORT",
        "UXV_TTS_MODEL",
        "UXV_TTS_VOICES",
        "UXV_TTS_VOICE",
        "UXV_TTS_LANGUAGE",
        "UXV_TTS_MAX_TEXT_CHARS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_load_config_uses_documented_defaults_when_env_is_unset(monkeypatch) -> None:
    _clear_tts_env(monkeypatch)

    config = load_config()

    assert config.host == "127.0.0.1"
    assert config.port == 9101
    assert config.model_path == DEFAULT_MODEL_PATH
    assert config.voices_path == DEFAULT_VOICES_PATH
    assert config.default_voice == "af_sky"
    assert config.default_language == "en-us"
    assert config.max_text_chars == 6000


def test_load_config_reads_every_field_from_env(monkeypatch, tmp_path: Path) -> None:
    _clear_tts_env(monkeypatch)
    model_path = tmp_path / "model.onnx"
    voices_path = tmp_path / "voices.bin"
    monkeypatch.setenv("UXV_TTS_HOST", "0.0.0.0")
    monkeypatch.setenv("UXV_TTS_PORT", "9200")
    monkeypatch.setenv("UXV_TTS_MODEL", str(model_path))
    monkeypatch.setenv("UXV_TTS_VOICES", str(voices_path))
    monkeypatch.setenv("UXV_TTS_VOICE", "bm_george")
    monkeypatch.setenv("UXV_TTS_LANGUAGE", "fr-fr")
    monkeypatch.setenv("UXV_TTS_MAX_TEXT_CHARS", "42")

    config = load_config()

    assert config.host == "0.0.0.0"
    assert config.port == 9200
    assert config.model_path == model_path
    assert config.voices_path == voices_path
    assert config.default_voice == "bm_george"
    assert config.default_language == "fr-fr"
    assert config.max_text_chars == 42


def test_load_config_falls_back_to_default_port_on_non_numeric_env(monkeypatch) -> None:
    _clear_tts_env(monkeypatch)
    monkeypatch.setenv("UXV_TTS_PORT", "not-a-number")

    config = load_config()

    assert config.port == 9101


def test_load_config_falls_back_to_default_max_text_chars_on_non_numeric_env(monkeypatch) -> None:
    _clear_tts_env(monkeypatch)
    monkeypatch.setenv("UXV_TTS_MAX_TEXT_CHARS", "")

    config = load_config()

    assert config.max_text_chars == 6000


def test_load_config_expands_user_in_model_and_voices_paths(monkeypatch) -> None:
    _clear_tts_env(monkeypatch)
    monkeypatch.setenv("UXV_TTS_MODEL", "~/kokoro/model.onnx")
    monkeypatch.setenv("UXV_TTS_VOICES", "~/kokoro/voices.bin")
    monkeypatch.setenv("HOME", "/home/tester")

    config = load_config()

    assert "~" not in str(config.model_path)
    assert "~" not in str(config.voices_path)


def test_model_ready_true_only_when_both_files_exist(tmp_path: Path) -> None:
    from config import TTSConfig

    model_path = tmp_path / "model.onnx"
    voices_path = tmp_path / "voices.bin"
    config = TTSConfig(
        host="127.0.0.1",
        port=9101,
        model_path=model_path,
        voices_path=voices_path,
        default_voice="af_sky",
        default_language="en-us",
        max_text_chars=6000,
    )
    assert config.model_ready is False

    model_path.write_bytes(b"")
    assert config.model_ready is False

    voices_path.write_bytes(b"")
    assert config.model_ready is True
