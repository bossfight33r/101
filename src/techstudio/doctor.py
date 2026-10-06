"""studio doctor: проверка внешних компонентов. Секреты не печатает — только «задан/нет»."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from techstudio.config import Settings
from techstudio.core import ffmpeg


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    hint: str = ""
    required: bool = True


def _run(cmd: list[str], timeout: int = 15) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def check_ffmpeg() -> list[Check]:
    if not ffmpeg.available():
        return [Check("ffmpeg", False, "нет в PATH", "brew install ffmpeg")]
    enc, flt = ffmpeg.list_encoders(), ffmpeg.list_filters()
    return [
        Check("ffmpeg", True, "ffmpeg/ffprobe найдены"),
        Check("ffmpeg libx264", "libx264" in enc, hint="ffmpeg собран без libx264"),
        Check(
            "ffmpeg h264_videotoolbox",
            "h264_videotoolbox" in enc,
            hint="только Мак; иначе libx264",
            required=False,
        ),
        Check("ffmpeg ass (libass)", " ass " in flt, hint="нужен ffmpeg с libass для шортсов"),
        Check("ffmpeg sidechaincompress", "sidechaincompress" in flt, required=False),
    ]


def check_docker(s: Settings) -> list[Check]:
    if shutil.which(s.docker_bin) is None:
        return [
            Check("docker", False, "нет в PATH", "Docker Desktop / OrbStack"),
            Check("sandbox image", False, s.sandbox_image, "make sandbox-image"),
            Check("VHS (в образе)", False, "нужен docker"),
        ]
    info = _run([s.docker_bin, "info", "--format", "{{.ServerVersion}}"])
    daemon = bool(info and info.returncode == 0)
    checks = [Check("docker daemon", daemon, (info.stdout.strip() if daemon else "не запущен"))]
    img = daemon and _run([s.docker_bin, "image", "inspect", s.sandbox_image])
    img_ok = bool(img and img.returncode == 0)
    checks.append(Check("sandbox image", img_ok, s.sandbox_image, "make sandbox-image"))
    vhs = img_ok and _run([s.docker_bin, "run", "--rm", s.sandbox_image, "--version"], 60)
    checks.append(
        Check("VHS (в образе)", bool(vhs and vhs.returncode == 0), "", "make sandbox-image")
    )
    return checks


def check_mermaid(s: Settings) -> Check:
    if shutil.which(s.mermaid_bin):
        return Check("mermaid-cli", True, f"локальный {s.mermaid_bin}")
    if shutil.which(s.docker_bin):
        img = _run([s.docker_bin, "image", "inspect", s.mermaid_image])
        if img and img.returncode == 0:
            return Check("mermaid-cli", True, f"docker {s.mermaid_image}")
    return Check(
        "mermaid-cli",
        False,
        "нет mmdc и образа",
        f"docker pull {s.mermaid_image}  (или npm i -g @mermaid-js/mermaid-cli)",
    )


def check_piper(s: Settings) -> list[Check]:
    checks = [
        Check(
            "piper",
            shutil.which(s.piper_bin) is not None,
            s.piper_bin,
            "uv pip install piper-tts (или бинарь piper)",
        )
    ]
    try:
        voice = s.voices.voice(s.channel.voice_id)
        exists = Path(voice.model).exists()
        checks.append(
            Check(f"голос {s.channel.voice_id}", exists, voice.model, "см. runbook.md#piper")
        )
    except Exception as e:  # noqa: BLE001
        checks.append(Check("голос", False, str(e)))
    return checks


def check_fonts(s: Settings) -> list[Check]:
    from PIL import ImageFont

    out = []
    st = s.channel.style
    for label, path in (("шрифт", st.font), ("жирный", st.font_bold), ("моно", st.mono_font)):
        try:
            font = ImageFont.truetype(path, 40)
            ok = font.getlength("Жж") > 0 and font.getmask("Ж").getbbox() is not None
            out.append(Check(f"{label} (кириллица)", ok, path))
        except OSError:
            out.append(Check(f"{label} (кириллица)", False, path, "поправь style.* в channel.yaml"))
    return out


def check_python() -> list[Check]:
    return [
        Check(
            "faster-whisper",
            importlib.util.find_spec("faster_whisper") is not None,
            hint='uv pip install -e ".[asr]"',
            required=False,
        ),
        Check(
            "mlx-whisper",
            importlib.util.find_spec("mlx_whisper") is not None,
            hint="только Мак: make setup-mac",
            required=False,
        ),
    ]


def check_secrets(s: Settings) -> list[Check]:
    return [
        Check(
            "ANTHROPIC_API_KEY",
            s.anthropic_api_key is not None,
            "задан" if s.anthropic_api_key else "не задан",
            ".env",
        ),
        Check(
            "TELEGRAM_BOT_TOKEN",
            s.telegram_bot_token is not None,
            "задан" if s.telegram_bot_token else "не задан",
            ".env",
            required=False,
        ),
        Check(
            "TS_ADMIN_IDS",
            bool(s.admin_id_set),
            f"{len(s.admin_id_set)} id",
            ".env",
            required=False,
        ),
        Check(
            "YouTube client secrets",
            s.resolve(s.youtube_client_secrets).exists(),
            str(s.youtube_client_secrets),
            "runbook.md#youtube",
            required=False,
        ),
    ]


def run_all(s: Settings) -> list[Check]:
    return [
        *check_ffmpeg(),
        *check_docker(s),
        check_mermaid(s),
        *check_piper(s),
        *check_fonts(s),
        *check_python(),
        *check_secrets(s),
    ]
