"""Мой ассет (скриншот/фото) + плавный Ken Burns. Нет ассета — fallback-слайд с предупреждением."""

from __future__ import annotations

from PIL import Image, ImageDraw

from techstudio.render import draw
from techstudio.render.base import RenderEnv, finish, size_of, still_to_video
from techstudio.render.slide import fallback_slide
from techstudio.schemas import Aspect, ImageScene, SceneRender


class ImageRenderer:
    name = "image"
    version = 1

    def __init__(self, env: RenderEnv):
        self.env = env

    def min_duration(self, scene) -> float:
        return 2.0

    def compose(self, scene: ImageScene, aspect: Aspect, src: Image.Image):
        st = self.env.style
        w, h = size_of(aspect)
        img = draw.cover_blur(src, (w, h))
        cap_h = 0
        if scene.caption:
            cap_font = draw.font(st.font_bold, 54 if aspect == "9x16" else 46)
            cap_lines = draw.wrap(scene.caption, cap_font, w - 160)
            cap_h = len(cap_lines) * int(cap_font.size * 1.3) + 60
        box = (int(w * 0.9), int((h - cap_h) * 0.88))
        fg = draw.contain(src.convert("RGB"), box)
        x, y = (w - fg.width) // 2, max((h - cap_h - fg.height) // 2, 20)
        img.paste(fg, (x, y))
        if scene.caption:
            d = ImageDraw.Draw(img)
            top = h - cap_h
            d.rectangle([0, top, w, h], fill=draw.rgb(st.bg))
            d.rectangle([0, top, w, top + 8], fill=draw.rgb(st.accent))
            ty = top + 30
            for line in cap_lines:
                d.text((80, ty), line, font=cap_font, fill=draw.rgb(st.fg))
                ty += int(cap_font.size * 1.3)
        return img

    def render(self, scene: ImageScene, aspect: Aspect, duration_hint: float) -> SceneRender:
        path = self.env.storage.path(scene.asset_key)
        if not path.exists():
            return fallback_slide(
                self.env,
                scene.id,
                aspect,
                duration_hint,
                scene.caption or "Скриншот",
                [f"нет файла {scene.asset_key}"],
                f"image: нет ассета {scene.asset_key} — показан запасной слайд",
            )
        with Image.open(path) as src:
            img = self.compose(scene, aspect, src)
        png = draw.save(img, self.env.scene_dir(scene.id) / f"frames_{aspect}" / "image.png")
        out = self.env.visual_path(scene.id, aspect)
        still_to_video(png, out, aspect, max(duration_hint, 1.0), self.env.encoder, zoom=1.08)
        return finish(self.env, scene.id, aspect, out)
