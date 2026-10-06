"""Диаграмма: mermaid-cli (локальный mmdc или Docker-образ) → PNG → стиль канала → лёгкий zoom.
Ошибка рендера — fallback-слайд с предупреждением на финальном ревью."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

from PIL import Image

from techstudio.render import draw
from techstudio.render.base import RenderEnv, finish, size_of, still_to_video
from techstudio.render.slide import fallback_slide
from techstudio.schemas import Aspect, DiagramScene, SceneRender


class MermaidError(RuntimeError):
    pass


class MermaidRunner(Protocol):
    name: str

    def render_png(self, source: str, out: Path, width: int, height: int) -> Path: ...


def _mmdc_args(inp: str, out: str, width: int, height: int) -> list[str]:
    return [
        "-i",
        inp,
        "-o",
        out,
        "-w",
        str(width),
        "-H",
        str(height),
        "-b",
        "transparent",
        "-t",
        "dark",
        "-s",
        "2",
    ]


class LocalMmdc:
    name = "mmdc"

    def __init__(self, binary: str = "mmdc", timeout: int = 120):
        self.binary = binary
        self.timeout = timeout

    def render_png(self, source: str, out: Path, width: int, height: int) -> Path:
        out.parent.mkdir(parents=True, exist_ok=True)
        src = out.with_suffix(".mmd")
        src.write_text(source, encoding="utf-8")
        proc = subprocess.run(
            [self.binary, *_mmdc_args(str(src), str(out), width, height)],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        if proc.returncode != 0 or not out.exists():
            raise MermaidError((proc.stderr or proc.stdout).strip()[-400:] or "mmdc failed")
        return out


class DockerMmdc:
    """minlag/mermaid-cli: без сети, non-root, монтируется только рабочая папка."""

    name = "mermaid-docker"

    def __init__(
        self,
        image: str = "minlag/mermaid-cli:latest",
        docker_bin: str = "docker",
        timeout: int = 180,
    ):
        self.image = image
        self.docker_bin = docker_bin
        self.timeout = timeout

    def build_args(self, workdir: Path, width: int, height: int) -> list[str]:
        return [
            self.docker_bin,
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "1000:1000",
            "--memory",
            "1g",
            "--cap-drop",
            "ALL",
            "-v",
            f"{workdir.resolve()}:/data",
            self.image,
            *_mmdc_args("/data/diagram.mmd", "/data/diagram.png", width, height),
        ]

    def render_png(self, source: str, out: Path, width: int, height: int) -> Path:
        workdir = out.parent
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / "diagram.mmd").write_text(source, encoding="utf-8")
        proc = subprocess.run(
            self.build_args(workdir, width, height),
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        produced = workdir / "diagram.png"
        if proc.returncode != 0 or not produced.exists():
            raise MermaidError((proc.stderr or proc.stdout).strip()[-400:] or "mermaid-cli failed")
        if produced != out:
            shutil.move(produced, out)
        return out


def find_runner(mermaid_bin: str, docker_bin: str, image: str) -> MermaidRunner | None:
    if shutil.which(mermaid_bin):
        return LocalMmdc(mermaid_bin)
    if shutil.which(docker_bin):
        try:
            proc = subprocess.run(
                [docker_bin, "image", "inspect", image],
                capture_output=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode == 0:
            return DockerMmdc(image, docker_bin)
    return None


def make_checker(runner: MermaidRunner):
    """Проверка синтаксиса при валидации сценария, если рендерер доступен."""

    def check(source: str) -> str | None:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                runner.render_png(source, Path(tmp) / "check.png", 800, 600)
            except (MermaidError, subprocess.TimeoutExpired) as e:
                return str(e)[:300]
        return None

    return check


class DiagramRenderer:
    name = "diagram"
    version = 1

    def __init__(self, env: RenderEnv, runner: MermaidRunner | None):
        self.env = env
        self.runner = runner

    def min_duration(self, scene) -> float:
        return 2.5

    def compose(self, png: Path, aspect: Aspect) -> Image.Image:
        w, h = size_of(aspect)
        img = draw.canvas((w, h), self.env.style)
        with Image.open(png) as d:
            dia = draw.contain(d.convert("RGBA"), (int(w * 0.86), int(h * 0.8)))
        img.paste(dia, ((w - dia.width) // 2, (h - dia.height) // 2), dia)
        return img

    def render(self, scene: DiagramScene, aspect: Aspect, duration_hint: float) -> SceneRender:
        w, h = size_of(aspect)
        sdir = self.env.scene_dir(scene.id) / f"frames_{aspect}"
        try:
            if self.runner is None:
                raise MermaidError("mermaid-cli недоступен")
            raw = self.runner.render_png(scene.mermaid, sdir / "mermaid.png", w, h)
            png = draw.save(self.compose(raw, aspect), sdir / "diagram.png")
        except (MermaidError, OSError, subprocess.TimeoutExpired) as e:
            lines = [ln.strip() for ln in scene.mermaid.splitlines()[1:] if ln.strip()]
            return fallback_slide(
                self.env,
                scene.id,
                aspect,
                duration_hint,
                "Схема",
                lines,
                f"diagram: fallback-слайд ({str(e)[:120]})",
            )
        out = self.env.visual_path(scene.id, aspect)
        still_to_video(png, out, aspect, max(duration_hint, 1.0), self.env.encoder, zoom=1.05)
        return finish(self.env, scene.id, aspect, out)
