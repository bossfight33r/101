"""Диаграмма: mermaid-cli (локальный mmdc или Docker-образ) → PNG → стиль канала → лёгкий zoom.
Ошибка рендера — fallback-слайд с предупреждением на финальном ревью."""

from __future__ import annotations

import re
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


def error_summary(output: str, default: str = "mermaid-cli failed") -> str:
    """Из вывода mmdc — строки ошибки до стектрейса (Parse error, позиция, ожидалось)."""
    lines = [ln.rstrip() for ln in output.splitlines()]
    start = next((i for i, ln in enumerate(lines) if "error" in ln.lower()), None)
    if start is None:
        return output.strip()[-300:] or default
    out = []
    for ln in lines[start:]:
        if ln.lstrip().startswith("at ") or ".mjs:" in ln or ".js:" in ln:
            break
        out.append(ln)
    return "\n".join(out)[:400] or default


class MermaidRunner(Protocol):
    name: str

    def render_png(self, source: str, out: Path, width: int, height: int) -> Path: ...


def _mmdc_args(inp: str, out: str, width: int, height: int) -> list[str]:
    """Флаги, общие для mmdc 10–12 (в 12 нет -w/-H). Размер под кадр подгоняет Pillow; scale — чёткость."""
    scale = 3 if max(width, height) >= 1500 else 2
    return ["-i", inp, "-o", out, "-b", "transparent", "-t", "dark", "-s", str(scale)]


class LocalMmdc:
    name = "mmdc"

    def __init__(
        self, binary: str = "mmdc", timeout: int = 120, puppeteer_config: str | None = None
    ):
        self.binary = binary
        self.timeout = timeout
        self.puppeteer_config = puppeteer_config

    def render_png(self, source: str, out: Path, width: int, height: int) -> Path:
        out.parent.mkdir(parents=True, exist_ok=True)
        src = out.with_suffix(".mmd")
        src.write_text(source, encoding="utf-8")
        extra = ["-p", self.puppeteer_config] if self.puppeteer_config else []
        proc = subprocess.run(
            [self.binary, *_mmdc_args(str(src), str(out), width, height), *extra],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        if proc.returncode != 0 or not out.exists():
            raise MermaidError(
                error_summary((proc.stderr or "") + (proc.stdout or ""), "mmdc failed")
            )
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
            raise MermaidError(error_summary((proc.stderr or "") + (proc.stdout or "")))
        if produced != out:
            shutil.move(produced, out)
        return out


_DIRECTION = re.compile(r"^(\s*(?:graph|flowchart))\s+(LR|RL)\b", re.M)


def orient(source: str, aspect: str) -> str:
    """9:16: горизонтальные flowchart (LR/RL) разворачиваем вертикально (TD/BT) — иначе мелко."""
    if aspect != "9x16":
        return source
    return _DIRECTION.sub(
        lambda m: f"{m.group(1)} {'TD' if m.group(2) == 'LR' else 'BT'}", source, count=1
    )


def find_runner(
    mermaid_bin: str, docker_bin: str, image: str, puppeteer_config: str | None = None
) -> MermaidRunner | None:
    if shutil.which(mermaid_bin):
        return LocalMmdc(mermaid_bin, puppeteer_config=puppeteer_config)
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
            raw = self.runner.render_png(orient(scene.mermaid, aspect), sdir / "mermaid.png", w, h)
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
