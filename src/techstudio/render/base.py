"""Интерфейс рендерера и общие ffmpeg-хелперы (кадры -> mp4, still -> mp4 с zoom)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from techstudio.core import ffmpeg, probe
from techstudio.core.encoder import Encoder, select
from techstudio.core.storage import LocalStorage
from techstudio.schemas import ASPECT_SIZE, Aspect, ChannelStyle, SceneRender

FPS = 30


@dataclass
class RenderEnv:
    storage: LocalStorage
    video_dir: Path  # data/studio/videos/{video_id}
    style: ChannelStyle
    encoder: Encoder = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.encoder is None:
            self.encoder = select("auto")

    def scene_dir(self, scene_id: str) -> Path:
        d = self.video_dir / "scenes" / scene_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def visual_path(self, scene_id: str, aspect: Aspect) -> Path:
        return self.scene_dir(scene_id) / f"visual_{aspect}.mp4"


class Renderer(Protocol):
    name: str
    version: int

    def render(self, scene, aspect: Aspect, duration_hint: float) -> SceneRender: ...

    def min_duration(self, scene) -> float:
        """Минимум, который нужен визуалу (набор команд, построчное появление)."""
        ...


def size_of(aspect: Aspect) -> tuple[int, int]:
    return ASPECT_SIZE[aspect]


def finish(
    env: RenderEnv, scene_id: str, aspect: Aspect, out: Path, warnings: list[str] | None = None
) -> SceneRender:
    w, h = size_of(aspect)
    info = probe.validate_video(out, width=w, height=h, min_duration=0.3)
    return SceneRender(
        scene_id=scene_id,
        aspect=aspect,
        video_key=env.storage.key(out),
        duration=round(info.duration, 3),
        warnings=warnings or [],
    )


def frames_to_video(
    frames: list[tuple[Path, float]], out: Path, aspect: Aspect, encoder: Encoder
) -> Path:
    """Последовательность PNG с длительностями -> mp4 (concat demuxer)."""
    if not frames:
        raise ValueError("нет кадров")
    w, h = size_of(aspect)
    lst = out.with_suffix(".frames.txt")
    lines = []
    for path, dur in frames:
        lines.append(ffmpeg.concat_line(path))
        lines.append(f"duration {max(dur, 1 / FPS):.3f}")
    lines.append(ffmpeg.concat_line(frames[-1][0]))  # требование concat demuxer
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    total = sum(max(d, 1 / FPS) for _, d in frames)
    ffmpeg.run(
        [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(lst),
            "-vf",
            f"scale={w}:{h}:flags=lanczos,fps={FPS},format=yuv420p",
            "-t",
            f"{total:.3f}",
            *encoder.args(fps=FPS),
            "-an",
            str(out),
        ]
    )
    lst.unlink(missing_ok=True)
    return out


def still_to_video(
    image: Path, out: Path, aspect: Aspect, duration: float, encoder: Encoder, zoom: float = 1.06
) -> Path:
    """Картинка -> mp4 с лёгким плавным zoom (Ken Burns к центру)."""
    w, h = size_of(aspect)
    frames = max(int(round(duration * FPS)), 1)
    step = (zoom - 1.0) / frames
    vf = (
        f"scale={w * 2}:{h * 2}:flags=lanczos,"
        f"zoompan=z='min(1+{step:.6f}*on,{zoom})':d={frames}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={FPS},format=yuv420p"
    )
    ffmpeg.run(
        [
            "-loop",
            "1",
            "-i",
            str(image),
            "-vf",
            vf,
            "-frames:v",
            str(frames),
            *encoder.args(fps=FPS),
            "-an",
            str(out),
        ]
    )
    return out
