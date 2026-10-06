"""3 варианта миниатюры 1280x720: крупный текст 3–5 слов, высокий контраст. Выбирает Босс."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from techstudio.core import ffmpeg
from techstudio.render import draw
from techstudio.schemas import ChannelStyle, ThumbnailVariant

SIZE = (1280, 720)
VARIANTS = ("A", "B", "C")


def clamp_words(text: str, lo: int = 3, hi: int = 5) -> str:
    words = text.replace("\n", " ").split()
    return " ".join(words[:hi]).upper() if len(words) >= lo else " ".join(words).upper()


def texts_for(title: str, suggested: list[str]) -> list[str]:
    out = [clamp_words(t) for t in suggested if t.strip()][:3]
    base = clamp_words(title)
    while len(out) < 3:
        out.append(base)
    return out


def grab_frame(video: Path, out: Path, at: float) -> Path | None:
    try:
        ffmpeg.run(["-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1", str(out)])
    except ffmpeg.FFmpegError:
        return None
    return out if out.exists() else None


def _text_block(
    d: ImageDraw.ImageDraw, text: str, style: ChannelStyle, box: tuple[int, int, int, int], color
) -> None:
    x0, y0, x1, y1 = box
    fnt, lines = draw.fit_font(text, style.font_bold, x1 - x0, y1 - y0, 150, 56, spacing=1.12)
    line_h = int(fnt.size * 1.12)
    y = y0 + max((y1 - y0 - line_h * len(lines)) // 2, 0)
    for line in lines:
        d.text((x0, y), line, font=fnt, fill=color, stroke_width=8, stroke_fill=(0, 0, 0))
        y += line_h


def render_variant(
    variant: str, text: str, style: ChannelStyle, frame: Path | None, out: Path
) -> Path:
    w, h = SIZE
    accent, fg = draw.rgb(style.accent), draw.rgb(style.fg)
    if variant == "A" or frame is None:
        # A: текст на акцентном фоне
        img = Image.new("RGB", SIZE, draw.rgb(style.bg))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, 40, h], fill=accent)
        _text_block(d, text, style, (90, 60, w - 60, h - 60), fg)
        if variant != "A":
            d.rectangle([w - 220, h - 70, w - 40, h - 50], fill=accent)
    else:
        with Image.open(frame) as f:
            shot = f.convert("RGB")
        if variant == "B":
            # B: кадр справа, текст слева на тёмной плашке
            img = draw.cover_blur(shot, SIZE, darken=0.6)
            fg_shot = draw.contain(shot, (int(w * 0.55), int(h * 0.8)))
            img.paste(fg_shot, (w - fg_shot.width - 40, (h - fg_shot.height) // 2))
            d = ImageDraw.Draw(img)
            d.rectangle([0, 0, int(w * 0.5), h], fill=draw.rgb(style.bg))
            d.rectangle([int(w * 0.5) - 12, 0, int(w * 0.5), h], fill=accent)
            _text_block(d, text, style, (50, 50, int(w * 0.5) - 40, h - 50), fg)
        else:
            # C: кадр на весь фон, текст снизу на акцентной полосе
            img = draw.cover_blur(shot, SIZE, darken=0.25)
            d = ImageDraw.Draw(img)
            d.rectangle([0, int(h * 0.58), w, h], fill=accent)
            _text_block(d, text, style, (50, int(h * 0.6), w - 50, h - 30), (10, 10, 10))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=92)
    return out


def render_all(
    title: str, suggested: list[str], style: ChannelStyle, frame: Path | None, out_dir: Path, key_of
) -> list[ThumbnailVariant]:
    variants = []
    for vid, text in zip(VARIANTS, texts_for(title, suggested), strict=True):
        path = render_variant(vid, text, style, frame, out_dir / f"{vid}.jpg")
        variants.append(ThumbnailVariant(id=vid, image_key=key_of(path), text=text))
    return variants
