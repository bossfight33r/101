"""FakeTTS: тихий тон длительностью ~ слова / wpm. Без сети и моделей."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from techstudio.config import VoiceConfig

RATE = 22050


class FakeTTS:
    name = "fake"

    def __init__(self, words_per_minute: int = 150):
        self.wpm = words_per_minute
        self.calls: list[str] = []

    def duration_for(self, text: str) -> float:
        return round(len(text.split()) * 60.0 / self.wpm + 0.2, 3)

    def synthesize(self, text: str, voice: VoiceConfig, out: Path) -> Path:
        self.calls.append(text)
        dur = self.duration_for(text)
        n = int(dur * RATE)
        out.parent.mkdir(parents=True, exist_ok=True)
        frames = bytearray()
        for i in range(n):
            # 220 Гц с огибающей «слогов», чтобы loudnorm было что мерить
            env = 0.5 + 0.5 * math.sin(2 * math.pi * 3 * i / RATE)
            frames += struct.pack("<h", int(6000 * env * math.sin(2 * math.pi * 220 * i / RATE)))
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(bytes(frames))
        return out
