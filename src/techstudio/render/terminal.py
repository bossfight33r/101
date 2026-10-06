"""Терминал: VHS tape из сцены → запуск VHS в Docker-песочнице → нормализация mp4 под ориентацию.

live   — команды реально выполняются в контейнере (вывод настоящий).
replay — команда набирается, но не выполняется: bash extdebug + DEBUG trap печатает файл с реальным
         выводом Босса с устройства (ADR 0004).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from techstudio.core import ffmpeg
from techstudio.render.base import FPS, RenderEnv, finish, size_of
from techstudio.sandbox import policy
from techstudio.sandbox.docker import DockerSandbox, SandboxError
from techstudio.schemas import Aspect, SceneRender, TerminalScene

SETUP_SHOW = 0.5  # пауза перед первой командой
AFTER_TYPE = 0.3  # пауза между набором и Enter
WAIT_OUTPUT = 2.0  # ожидание вывода после Enter
MIN_TAIL = 1.0

TAPE_SETTINGS = {
    "16x9": {"width": 1920, "height": 1080, "font": 30, "padding": 48},
    "9x16": {"width": 1080, "height": 1920, "font": 38, "padding": 40},
}

REPLAY_INIT = r"""HISTCONTROL=
HISTIGNORE=
PROMPT_COMMAND=
__ts_dir="/out/replay"
__ts_n=0
__ts_last=""
__ts_replay() {
  if [[ "$HISTCMD" != "$__ts_last" ]]; then
    __ts_last="$HISTCMD"
    [[ -f "$__ts_dir/$__ts_n.txt" ]] && cat "$__ts_dir/$__ts_n.txt"
    __ts_n=$((__ts_n + 1))
  fi
  return 1
}
clear
shopt -s extdebug
trap '__ts_replay' DEBUG
"""


class TapeError(ValueError):
    pass


def quote_vhs(text: str) -> str:
    for q in ('"', "'", "`"):
        if q not in text:
            return f"{q}{text}{q}"
    raise TapeError(f"команда содержит все виды кавычек — VHS не наберёт её: {text}")


def typing_time(scene: TerminalScene) -> float:
    per_cmd = [
        len(c) * scene.typing_speed / 1000 + AFTER_TYPE + WAIT_OUTPUT for c in scene.commands
    ]
    return SETUP_SHOW + sum(per_cmd)


def build_tape(
    scene: TerminalScene,
    aspect: Aspect,
    duration: float,
    theme: str,
    output: str = "/out/visual.mp4",
) -> str:
    cfg = TAPE_SETTINGS[aspect]
    tail = max(duration - typing_time(scene), MIN_TAIL)
    lines = [
        f"Output {output}",
        'Set Shell "bash"',
        f"Set Width {cfg['width']}",
        f"Set Height {cfg['height']}",
        f"Set FontSize {cfg['font']}",
        f"Set Padding {cfg['padding']}",
        f"Set Framerate {FPS}",
        f"Set Theme {quote_vhs(theme)}",
        f"Set TypingSpeed {scene.typing_speed}ms",
        "Set WindowBar Colorful",
        "Hide",
    ]
    if scene.mode == "replay":
        lines += ['Type "source /out/replay_init.sh"', "Enter"]
    else:
        lines += ['Type "cd ~ && clear"', "Enter"]
    lines += ["Sleep 500ms", "Show", f"Sleep {int(SETUP_SHOW * 1000)}ms"]
    for cmd in scene.commands:
        lines += [
            f"Type {quote_vhs(cmd)}",
            f"Sleep {int(AFTER_TYPE * 1000)}ms",
            "Enter",
            f"Sleep {int(WAIT_OUTPUT * 1000)}ms",
        ]
    lines.append(f"Sleep {int(tail * 1000)}ms")
    return "\n".join(lines) + "\n"


def stage_replay(env: RenderEnv, scene: TerminalScene, workdir: Path) -> None:
    """Файлы реального вывода → workdir/replay/N.txt. Ключ — папка с 0.txt.. или один файл."""
    rdir = workdir / "replay"
    rdir.mkdir(parents=True, exist_ok=True)
    key = scene.replay_output_key
    base = env.storage.path(key)
    single = base if base.is_file() else env.storage.path(key + ".txt")
    if base.is_dir():
        found = 0
        for i in range(len(scene.commands)):
            src = base / f"{i}.txt"
            if src.exists():
                shutil.copyfile(src, rdir / f"{i}.txt")
                found += 1
        if not found:
            raise SandboxError(f"replay: в {key}/ нет файлов 0.txt..{len(scene.commands) - 1}.txt")
    elif single.is_file():
        shutil.copyfile(single, rdir / "0.txt")
    else:
        raise SandboxError(f"replay: нет файла реального вывода {key}")
    (workdir / "replay_init.sh").write_text(REPLAY_INIT, encoding="utf-8")


def normalize(src: Path, out: Path, aspect: Aspect, env: RenderEnv) -> Path:
    w, h = size_of(aspect)
    ffmpeg.run(
        [
            "-i",
            str(src),
            "-vf",
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={FPS},format=yuv420p",
            *env.encoder.args(fps=FPS),
            "-an",
            str(out),
        ]
    )
    return out


class TerminalRenderer:
    name = "terminal"
    version = 1

    def __init__(self, env: RenderEnv, sandbox: DockerSandbox):
        self.env = env
        self.sandbox = sandbox

    def min_duration(self, scene: TerminalScene) -> float:
        return typing_time(scene) + MIN_TAIL

    def render(self, scene: TerminalScene, aspect: Aspect, duration_hint: float) -> SceneRender:
        blocking = policy.errors(policy.check_scene(scene))
        if blocking:
            raise SandboxError("policy: " + "; ".join(str(v) for v in blocking))
        workdir = self.env.scene_dir(scene.id) / f"vhs_{aspect}"
        if workdir.exists():
            shutil.rmtree(workdir)
        workdir.mkdir(parents=True)
        if scene.mode == "replay":
            stage_replay(self.env, scene, workdir)
        (workdir / "scene.tape").write_text(
            build_tape(scene, aspect, duration_hint, self.env.style.terminal_theme),
            encoding="utf-8",
        )
        self.sandbox.run(
            workdir, ["/out/scene.tape"], network=scene.network and scene.mode == "live"
        )
        raw = workdir / "visual.mp4"
        if not raw.exists():
            raise SandboxError("VHS не создал видео")
        out = self.env.visual_path(scene.id, aspect)
        normalize(raw, out, aspect, self.env)
        warnings = ["network: true — у песочницы была сеть"] if scene.network else []
        if scene.mode == "replay":
            warnings.append("replay: вывод из файла реального вывода")
        return finish(self.env, scene.id, aspect, out, warnings)
