"""Бэкенды кодирования H.264: videotoolbox (Мак) или libx264."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from techstudio.core import ffmpeg


@dataclass(frozen=True)
class Encoder:
    name: str
    video_args: tuple[str, ...]

    def args(self, *, fps: int = 30) -> list[str]:
        return [*self.video_args, "-pix_fmt", "yuv420p", "-r", str(fps)]


X264 = Encoder("x264", ("-c:v", "libx264", "-preset", "veryfast", "-crf", "20"))
X264_FAST = Encoder("x264_fast", ("-c:v", "libx264", "-preset", "ultrafast", "-crf", "28"))
VIDEOTOOLBOX = Encoder("videotoolbox", ("-c:v", "h264_videotoolbox", "-b:v", "8M"))

AUDIO_ARGS = ["-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]


@lru_cache(maxsize=1)
def _encoders_text() -> str:
    try:
        return ffmpeg.list_encoders()
    except Exception:  # noqa: BLE001 — нет ffmpeg: решит doctor
        return ""


def select(preference: str = "auto") -> Encoder:
    if preference == "x264":
        return X264
    if preference == "x264_fast":
        return X264_FAST
    if preference == "videotoolbox":
        return VIDEOTOOLBOX
    return VIDEOTOOLBOX if "h264_videotoolbox" in _encoders_text() else X264
