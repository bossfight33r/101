from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from techstudio.config import VoiceConfig


class TTSError(RuntimeError):
    pass


class TTSProvider(Protocol):
    name: str

    def synthesize(self, text: str, voice: VoiceConfig, out: Path) -> Path:
        """Синтез text в wav по пути out. Текст уже прошёл словарь произношения."""
        ...


def apply_pronunciation(text: str, mapping: dict[str, str]) -> str:
    """Замена терминов только для TTS (субтитры остаются в исходном написании).
    Длинные ключи первыми; границы слова, чтобы 'IP' не задевал 'IPv6'-подобное внутри слов."""
    for term in sorted(mapping, key=len, reverse=True):
        pattern = r"(?<![\w-])" + re.escape(term) + r"(?![\w-])"
        text = re.sub(pattern, mapping[term], text)
    return text
