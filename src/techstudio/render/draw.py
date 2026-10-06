"""Pillow-утилиты: шрифты, цвета, перенос текста по ширине в пикселях, фон."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from techstudio.schemas import ChannelStyle


def rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


@lru_cache(maxsize=64)
def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def wrap(text: str, fnt: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = words[0]
        for w in words[1:]:
            trial = f"{cur} {w}"
            if fnt.getlength(trial) <= max_width:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    # слишком длинное слово — режем по символам
    out: list[str] = []
    for line in lines:
        while fnt.getlength(line) > max_width and len(line) > 1:
            cut = len(line)
            while cut > 1 and fnt.getlength(line[:cut]) > max_width:
                cut -= 1
            out.append(line[:cut])
            line = line[cut:]
        out.append(line)
    return out


def fit_font(
    text: str,
    path: str,
    max_width: int,
    max_height: int,
    start: int,
    minimum: int,
    spacing: float = 1.25,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    size = start
    while True:
        fnt = font(path, size)
        lines = wrap(text, fnt, max_width)
        words_fit = all(fnt.getlength(w) <= max_width for w in text.split())
        if (words_fit and len(lines) * size * spacing <= max_height) or size <= minimum:
            return fnt, lines
        size -= 2


def canvas(size: tuple[int, int], style: ChannelStyle) -> Image.Image:
    """Фон канала: вертикальный градиент bg → чуть светлее."""
    w, h = size
    top = rgb(style.bg)
    bottom = tuple(min(255, int(c * 1.35) + 8) for c in top)
    img = Image.new("RGB", size, top)
    px = ImageDraw.Draw(img)
    for y in range(0, h, 4):
        t = y / h
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        px.rectangle([0, y, w, y + 4], fill=color)
    return img


def cover_blur(img: Image.Image, size: tuple[int, int], darken: float = 0.45) -> Image.Image:
    """Фон из самой картинки: cover + blur + затемнение."""
    w, h = size
    scale = max(w / img.width, h / img.height)
    bg = img.convert("RGB").resize((int(img.width * scale) + 1, int(img.height * scale) + 1))
    left, top = (bg.width - w) // 2, (bg.height - h) // 2
    bg = bg.crop((left, top, left + w, top + h)).filter(ImageFilter.GaussianBlur(28))
    return Image.blend(bg, Image.new("RGB", size, (0, 0, 0)), darken)


def contain(img: Image.Image, box: tuple[int, int]) -> Image.Image:
    bw, bh = box
    scale = min(bw / img.width, bh / img.height)
    return img.resize(
        (max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS
    )


def save(img: Image.Image, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")
    return path
