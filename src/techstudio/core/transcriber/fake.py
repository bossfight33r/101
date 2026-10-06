"""Фейк: раскладывает слова hint равномерно по длительности wav (без ffmpeg)."""

from __future__ import annotations

import wave
from pathlib import Path

from techstudio.schemas import Word


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


class FakeTranscriber:
    name = "fake"

    def __init__(self, lead: float = 0.05):
        self.lead = lead
        self.calls = 0

    def transcribe(self, audio: Path, *, language: str = "ru", hint: str = "") -> list[Word]:
        self.calls += 1
        tokens = hint.split()
        if not tokens:
            return []
        total = max(wav_duration(audio) - 2 * self.lead, 0.1)
        step = total / len(tokens)
        return [
            Word(
                text=t,
                start=round(self.lead + i * step, 3),
                end=round(self.lead + (i + 1) * step - 0.02, 3),
            )
            for i, t in enumerate(tokens)
        ]
