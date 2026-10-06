from __future__ import annotations

from pathlib import Path
from typing import Protocol

from techstudio.schemas import Word


class Transcriber(Protocol):
    name: str

    def transcribe(self, audio: Path, *, language: str = "ru", hint: str = "") -> list[Word]:
        """Пословный транскрипт. hint — текст, который озвучивался (для фейка/промпта)."""
        ...
