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


@pytest.fixture
def topic(svc):
    from techstudio.schemas import Topic

    t = Topic(
        id="ss-ports",
        title="ss: кто слушает порты",
        key_points=["ss -tuln", "фильтр по порту"],
        must_show_commands=["ss -tuln", "curl -I https://example.com"],
    )
    svc.db.upsert_topic(t)
    return t


@pytest.fixture
def small_channel(settings):
    """Канал с коротким окном длительности — e2e быстрее (реальный ffmpeg)."""
    from techstudio.schemas import LongformTarget

    ch = settings.channel.model_copy(update={"longform": LongformTarget(min_sec=40, max_sec=200)})
    settings.__dict__["channel"] = ch
    return ch
