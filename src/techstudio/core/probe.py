"""Типизированный ffprobe + валидация результата рендера."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from techstudio.core import ffmpeg


class MediaInfo(BaseModel):
    duration: float
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    vcodec: str | None = None
    acodec: str | None = None
    sample_rate: int | None = None

    @property
    def has_video(self) -> bool:
        return self.vcodec is not None

    @property
    def has_audio(self) -> bool:
        return self.acodec is not None


def _fps(rate: str | None) -> float | None:
    if not rate or rate == "0/0":
        return None
    num, _, den = rate.partition("/")
    return float(num) / float(den or 1)


def probe(path: Path) -> MediaInfo:
    data = ffmpeg.probe_json(path)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    duration = float(data.get("format", {}).get("duration") or (v or a or {}).get("duration") or 0)
    return MediaInfo(
        duration=duration,
        width=v.get("width") if v else None,
        height=v.get("height") if v else None,
        fps=_fps(v.get("avg_frame_rate")) if v else None,
        vcodec=v.get("codec_name") if v else None,
        acodec=a.get("codec_name") if a else None,
        sample_rate=int(a["sample_rate"]) if a and a.get("sample_rate") else None,
    )


class ValidationError(RuntimeError):
    pass


def validate_video(
    path: Path,
    *,
    width: int,
    height: int,
    min_duration: float = 0.5,
    expected_duration: float | None = None,
    tolerance: float = 0.5,
    need_audio: bool = False,
) -> MediaInfo:
    if not path.exists() or path.stat().st_size == 0:
        raise ValidationError(f"{path.name}: файл отсутствует или пуст")
    info = probe(path)
    if not info.has_video:
        raise ValidationError(f"{path.name}: нет видеопотока")
    if (info.width, info.height) != (width, height):
        raise ValidationError(
            f"{path.name}: {info.width}x{info.height}, ожидалось {width}x{height}"
        )
    if info.duration < min_duration:
        raise ValidationError(f"{path.name}: длительность {info.duration:.2f}s < {min_duration}s")
    if expected_duration is not None and abs(info.duration - expected_duration) > tolerance:
        raise ValidationError(
            f"{path.name}: длительность {info.duration:.2f}s, ожидалось {expected_duration:.2f}s"
        )
    if need_audio and not info.has_audio:
        raise ValidationError(f"{path.name}: нет аудиопотока")
    return info
