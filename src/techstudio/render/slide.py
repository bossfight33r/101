"""Слайд: заголовок + до 4 буллетов, появляются по одному. Шаблон из стиля канала."""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import ImageDraw

from techstudio.render import draw
from techstudio.render.base import RenderEnv, finish, frames_to_video, size_of
from techstudio.schemas import Aspect, SceneRender, SlideScene

TITLE_HOLD = 0.6


def compose(
    scene: SlideScene, aspect: Aspect, env: RenderEnv, visible: int, out: Path, subtitle: str = ""
) -> Path:
    st = env.style
    w, h = size_of(aspect)
    vertical = aspect == "9x16"
    img = draw.canvas((w, h), st)
    d = ImageDraw.Draw(img)
    margin = 90 if vertical else 140
    max_w = w - 2 * margin

    title_font, title_lines = draw.fit_font(
        scene.title, st.font_bold, max_w, int(h * 0.3), 96 if vertical else 84, 40
    )
    sub_font, sub_lines = (None, [])
    if subtitle:
        sub_font, sub_lines = draw.fit_font(
            subtitle, st.font, max_w, int(h * 0.3), 52 if vertical else 44, 26
        )
    bullet_size = 60 if vertical else 50
    bfont = draw.font(st.font, bullet_size)
    bullet_lines = [draw.wrap(b, bfont, max_w - 70) for b in scene.bullets]
    gap = int(bullet_size * (0.9 if vertical else 0.6))

    # высота всего блока (со всеми буллетами) — чтобы центрировать и не прыгать при появлении
    total = len(title_lines) * int(title_font.size * 1.2) + 18 + 10 + (70 if vertical else 60)
    if sub_font:
        total += len(sub_lines) * int(sub_font.size * 1.3)
    total += sum(len(bl) * int(bullet_size * 1.3) + gap for bl in bullet_lines)
    y = max((h - total) // 2, int(h * 0.08))

    for line in title_lines:
        d.text((margin, y), line, font=title_font, fill=draw.rgb(st.fg))
        y += int(title_font.size * 1.2)
    y += 18
    d.rectangle([margin, y, margin + 160, y + 10], fill=draw.rgb(st.accent))
    y += 70 if vertical else 60
    for line in sub_lines:
        d.text((margin, y), line, font=sub_font, fill=draw.rgb(st.muted))
        y += int(sub_font.size * 1.3)
    for lines in bullet_lines[:visible]:
        dot_y = y + bullet_size // 2
        d.ellipse([margin, dot_y - 11, margin + 22, dot_y + 11], fill=draw.rgb(st.accent))
        for line in lines:
            d.text((margin + 60, y), line, font=bfont, fill=draw.rgb(st.fg))
            y += int(bullet_size * 1.3)
        y += gap
    return draw.save(img, out)


class SlideRenderer:
    name = "slide"
    version = 1

    def __init__(self, env: RenderEnv):
        self.env = env

    def min_duration(self, scene) -> float:
        return TITLE_HOLD + 0.8 * len(scene.bullets) + 1.0

    def timeline(self, scene: SlideScene, duration: float) -> list[float]:
        """Длительности кадров: [только заголовок, +1 буллет, ...]."""
        n = len(scene.bullets)
        if n == 0:
            return [duration]
        reveal_span = max(duration * 0.6, TITLE_HOLD + 0.5 * n)
        step = (reveal_span - TITLE_HOLD) / n
        durs = [TITLE_HOLD] + [step] * (n - 1)
        durs.append(max(duration - sum(durs), 0.5))
        return durs

    def render(
        self, scene: SlideScene, aspect: Aspect, duration_hint: float, subtitle: str = ""
    ) -> SceneRender:
        sdir = self.env.scene_dir(scene.id) / f"frames_{aspect}"
        frames = []
        durs = self.timeline(scene, max(duration_hint, 1.0))
        start = 0 if scene.bullets else len(scene.bullets)
        for i, dur in enumerate(durs):
            visible = start + i
            frames.append(
                (compose(scene, aspect, self.env, visible, sdir / f"f{i:02d}.png", subtitle), dur)
            )
        out = self.env.visual_path(scene.id, aspect)
        frames_to_video(frames, out, aspect, self.env.encoder)
        shutil.rmtree(sdir, ignore_errors=True)  # PNG-кадры промежуточные: видео уже собрано
        return finish(self.env, scene.id, aspect, out)


def fallback_slide(
    env: RenderEnv,
    scene_id: str,
    aspect: Aspect,
    duration: float,
    title: str,
    lines: list[str],
    warning: str,
) -> SceneRender:
    """Запасной слайд вместо сломанного визуала. Предупреждение уйдёт на финальное ревью."""
    slide = SlideScene(
        id=scene_id, narration="-", title=title, bullets=[ln[:80] for ln in lines[:4]]
    )
    sdir = env.scene_dir(scene_id) / f"frames_{aspect}"
    png = compose(slide, aspect, env, len(slide.bullets), sdir / "fallback.png")
    out = env.visual_path(scene_id, aspect)
    frames_to_video([(png, max(duration, 1.0))], out, aspect, env.encoder)
    return finish(env, scene_id, aspect, out, warnings=[warning])
