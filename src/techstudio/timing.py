"""Тайминг: оценка длительности по словам, длительность сцены, выравнивание слов, подгонка визуала."""

from __future__ import annotations

import re

WORD_RE = re.compile(r"\S+")


def count_words(text: str) -> int:
    return len(WORD_RE.findall(text or ""))


def estimate_speech(text: str, wpm: int) -> float:
    return count_words(text) * 60.0 / wpm


def scene_duration(
    narration_sec: float,
    *,
    min_sec: float,
    visual_min: float,
    pause_before: float,
    pause_after: float,
) -> float:
    """Длительность сцены = max(озвучка + паузы, минимум сцены, минимум визуала)."""
    return round(max(narration_sec + pause_before + pause_after, min_sec, visual_min), 3)
