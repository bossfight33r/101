"""Длинное видео: сегменты сцен (визуал + озвучка) → concat 1920x1080 30fps → музыка/ducking → loudnorm."""

from __future__ import annotations

from pathlib import Path

from techstudio.assemble import music
from techstudio.core import ffmpeg
from techstudio.core.encoder import AUDIO_ARGS, Encoder

FADE = 0.25


def build_segment(
    visual: Path,
    narration: Path | None,
    out: Path,
    *,
    duration: float,
    pause_before: float,
    encoder: Encoder,
    fade: bool = False,
    visual_duration: float | None = None,
) -> Path:
    """Сегмент сцены: визуал + голос с паузой в начале, тишина до конца.
    Визуал короче сцены — freeze последнего кадра (tpad), длиннее — обрезаем хвост (-t)."""
    d = f"{duration:.3f}"
    if narration is not None:
        a_in = ["-i", str(narration)]
    else:
        a_in = ["-f", "lavfi", "-t", d, "-i", "anullsrc=r=48000:cl=stereo"]
    delay_ms = int(pause_before * 1000) if narration is not None else 0
    afilter = f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay={delay_ms}:all=1,apad=whole_dur={d}[a]"
    vfilter = "[0:v]"
    if visual_duration is not None and visual_duration < duration - 0.02:
        vfilter += f"tpad=stop_mode=clone:stop_duration={duration - visual_duration + 0.1:.3f},"
    vfilter += "fps=30,format=yuv420p"
    if fade:
        vfilter += f",fade=t=in:st=0:d={FADE},fade=t=out:st={max(duration - FADE, 0):.3f}:d={FADE}"
    vfilter += "[v]"
    ffmpeg.run(
        [
            "-i",
            str(visual),
            *a_in,
            "-filter_complex",
            f"{vfilter};{afilter}",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-t",
            d,
            *encoder.args(fps=30),
            *AUDIO_ARGS,
            str(out),
        ]
    )
    return out


def concat(segments: list[Path], out: Path) -> Path:
    lst = out.with_suffix(".concat.txt")
    lst.write_text("".join(ffmpeg.concat_line(p) + "\n" for p in segments), encoding="utf-8")
    ffmpeg.run(
        [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(lst),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(out),
        ]
    )
    lst.unlink(missing_ok=True)
    return out


def finalize_audio(
    raw: Path, out: Path, *, total: float, track: Path | None, volume: float
) -> Path:
    """Видео копируется, звук: (музыка с ducking) + loudnorm -14 LUFS."""
    ffmpeg.run(
        [
            "-i",
            str(raw),
            *music.music_inputs(track),
            "-filter_complex",
            music.audio_filter(track is not None, volume),
            "-map",
            "0:v",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            *AUDIO_ARGS,
            "-t",
            f"{total:.3f}",
            "-movflags",
            "+faststart",
            str(out),
        ]
    )
    return out


def preview(src: Path, out: Path, *, height: int = 360) -> Path:
    """Сжатое превью для ревью в Telegram (лимит бота 50 МБ)."""
    ffmpeg.run(
        [
            "-i",
            str(src),
            "-vf",
            f"scale=-2:{height},fps=24",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "32",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-ac",
            "1",
            "-movflags",
            "+faststart",
            str(out),
        ]
    )
    return out
