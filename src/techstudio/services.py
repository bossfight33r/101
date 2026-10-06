"""Сборка зависимостей из Settings. Тесты подменяют поля Services фейками."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from techstudio.config import Settings
from techstudio.core.db import Database
from techstudio.core.storage import LocalStorage


def build_llm(s: Settings):
    if s.llm_provider == "fake":
        from techstudio.core.llm.fake import FakeLLM
        from techstudio.script.fake import default_responses

        return FakeLLM(default_responses())
    from techstudio.core.llm.anthropic import AnthropicLLM

    key = s.anthropic_api_key.get_secret_value() if s.anthropic_api_key else None
    return AnthropicLLM(model=s.llm_model, max_tokens=s.llm_max_tokens, api_key=key)


def build_tts(s: Settings):
    if s.tts == "fake":
        from techstudio.voice.fake import FakeTTS

        return FakeTTS()
    from techstudio.voice.piper import PiperTTS

    return PiperTTS(binary=s.piper_bin)


def build_transcriber(s: Settings):
    if s.transcriber == "fake":
        from techstudio.core.transcriber.fake import FakeTranscriber

        return FakeTranscriber()
    if s.transcriber == "mlx":
        from techstudio.core.transcriber.mlx import MlxWhisperTranscriber

        return MlxWhisperTranscriber()
    from techstudio.core.transcriber.faster_whisper import FasterWhisperTranscriber

    return FasterWhisperTranscriber(model=s.whisper_model)


@dataclass
class Services:
    settings: Settings
    storage: LocalStorage
    db: Database
    _llm: object = None
    _tts: object = None
    _transcriber: object = None
    overrides: dict = field(default_factory=dict)  # тесты: renderer/publisher/collector/...

    @classmethod
    def from_settings(cls, s: Settings | None = None) -> Services:
        s = s or Settings()
        root = s.resolve(s.data_dir)
        return cls(settings=s, storage=LocalStorage(root), db=Database(root / "studio.db"))

    @property
    def llm(self):
        if self._llm is None:
            self._llm = build_llm(self.settings)
        return self._llm

    @property
    def tts(self):
        if self._tts is None:
            self._tts = build_tts(self.settings)
        return self._tts

    @property
    def transcriber(self):
        if self._transcriber is None:
            self._transcriber = build_transcriber(self.settings)
        return self._transcriber

    @property
    def mermaid_checker(self):
        """Проверка синтаксиса mermaid реальным mermaid-cli, если он доступен (кешируется)."""
        if "_mermaid_checker" not in self.overrides:
            from techstudio.render.diagram import find_runner, make_checker

            s = self.settings
            runner = find_runner(s.mermaid_bin, s.docker_bin, s.mermaid_image)
            self.overrides["_mermaid_checker"] = make_checker(runner) if runner else None
        return self.overrides["_mermaid_checker"]

    @property
    def channel(self):
        return self.settings.channel

    def video_dir(self, video_id: str) -> Path:
        return self.storage.ensure_dir(f"videos/{video_id}")
