"""Шортсы 9:16: [карточка хука] + сцена + end-card → ASS-субтитры с подсветкой слова → loudnorm."""

from __future__ import annotations

from pathlib import Path

from techstudio.assemble import longform
from techstudio.core import captions, ffmpeg
from techstudio.core.encoder import AUDIO_ARGS, Encoder
from techstudio.schemas import ChannelStyle, Word

MAX_SHORT_SEC = 60.0
ENDCARD_SEC = 2.0


def burn(raw: Path, out: Path, words: list[Word], style: ChannelStyle, encoder: Encoder) -> Path:
    ass = out.with_name("captions.ass")
    ass.write_text(
        captions.to_ass(
            words, font=style.caption_font_name, color=style.fg, highlight=style.accent
        ),
        encoding="utf-8",
    )
    fonts_dir = Path(style.font).parent
    vf = f"ass={ffmpeg.escape_filter_path(ass)}:fontsdir={ffmpeg.escape_filter_path(fonts_dir)}"
    ffmpeg.run(
        [
            "-i",
            str(raw),
            "-vf",
            vf,
            "-af",
            "loudnorm=I=-14:TP=-1.0:LRA=11",
            *encoder.args(fps=30),
            *AUDIO_ARGS,
            "-movflags",
            "+faststart",
            str(out),
        ]
    )
    return out


def assemble_short(
    parts: list[Path], words: list[Word], out_dir: Path, style: ChannelStyle, encoder: Encoder
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = longform.concat(parts, out_dir / "raw.mp4")
    final = burn(raw, out_dir / "final.mp4", words, style, encoder)
    raw.unlink(missing_ok=True)
    return final
