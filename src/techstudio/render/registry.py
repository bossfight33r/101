"""Выбор рендереров по TS_RENDERERS: fake | real | auto (terminal → fake, если нет Docker-песочницы)."""

from __future__ import annotations

from techstudio.render.base import RenderEnv
from techstudio.render.code import CodeRenderer
from techstudio.render.diagram import DiagramRenderer, find_runner
from techstudio.render.fake import FakeRenderer
from techstudio.render.image import ImageRenderer
from techstudio.render.slide import SlideRenderer
from techstudio.render.terminal import TerminalRenderer
from techstudio.sandbox.docker import DockerSandbox, SandboxLimits


def build_sandbox(s) -> DockerSandbox:
    return DockerSandbox(
        image=s.sandbox_image,
        docker_bin=s.docker_bin,
        limits=SandboxLimits(
            cpus=s.sandbox_cpus,
            memory=s.sandbox_memory,
            pids=s.sandbox_pids,
            timeout=s.sandbox_timeout,
        ),
    )


def build_renderers(svc, env: RenderEnv) -> dict:
    """{тип сцены: рендерер}. svc.overrides['renderers'] = {type: callable(env)} — для тестов."""
    s = svc.settings
    overrides = svc.overrides.get("renderers", {})
    if s.renderers == "fake":
        fake = FakeRenderer(env)
        out = dict.fromkeys(("terminal", "code", "diagram", "slide", "image"), fake)
    else:
        sandbox = svc.overrides.get("sandbox") or build_sandbox(s)
        if s.renderers == "auto" and not sandbox.available():
            terminal = FakeRenderer(env)
            terminal.name = "fake-terminal"
        else:
            terminal = TerminalRenderer(env, sandbox, vhs_bin=s.vhs_bin)
        runner = svc.overrides.get(
            "mermaid_runner",
            find_runner(s.mermaid_bin, s.docker_bin, s.mermaid_image, s.mermaid_puppeteer_config),
        )
        out = {
            "terminal": terminal,
            "code": CodeRenderer(env),
            "diagram": DiagramRenderer(env, runner),
            "slide": SlideRenderer(env),
            "image": ImageRenderer(env),
        }
    for kind, factory in overrides.items():
        out[kind] = factory(env)
    return out
