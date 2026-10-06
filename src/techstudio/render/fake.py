"""Фейковый рендерер: ffmpeg color (дёшево) нужного размера. Для тестов и окружений без VHS/mermaid."""

from __future__ import annotations

from techstudio.core import ffmpeg
from techstudio.render.base import FPS, RenderEnv, finish, size_of
from techstudio.schemas import Aspect, SceneRender


class FakeRenderer:
    name = "fake"
    version = 1

    def __init__(self, env: RenderEnv, duration_factor: float = 1.0, min_sec: float = 0.0):
        self.env = env
        self.duration_factor = duration_factor
        self.min_sec = min_sec
        self.calls: list[tuple[str, str]] = []

    def min_duration(self, scene) -> float:
        return self.min_sec

    def render(self, scene, aspect: Aspect, duration_hint: float) -> SceneRender:
        self.calls.append((scene.id, aspect))
        w, h = size_of(aspect)
        dur = max(duration_hint * self.duration_factor, 0.5)
        out = self.env.visual_path(scene.id, aspect)
        ffmpeg.run(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x1e293b:size={w}x{h}:rate={FPS}:duration={dur:.3f}",
                *self.env.encoder.args(fps=FPS),
                "-an",
                str(out),
            ]
        )
        return finish(self.env, scene.id, aspect, out, warnings=["fake-визуал"])
