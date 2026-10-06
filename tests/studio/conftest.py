from __future__ import annotations

import shutil

import pytest

from techstudio.config import Settings
from techstudio.services import Services

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="нет ffmpeg")


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith("TS_") or key in ("ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        llm_provider="fake",
        tts="fake",
        transcriber="fake",
        renderers="fake",
        publisher="fake",
        collector="fake",
        encoder="x264_fast",
    )


@pytest.fixture
def svc(settings) -> Services:
    return Services.from_settings(settings)
