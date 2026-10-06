"""Единственная точка вызова ffmpeg/ffprobe. Остальной код строит аргументы и зовёт run()."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from techstudio.core import log

_log = log.get("ffmpeg")


class FFmpegError(RuntimeError):
    def __init__(self, message: str, stderr_tail: str = ""):
        super().__init__(message)
        self.stderr_tail = stderr_tail


def ffmpeg_bin() -> str:
    return os.environ.get("TS_FFMPEG", "ffmpeg")


def ffprobe_bin() -> str:
    return os.environ.get("TS_FFPROBE", "ffprobe")


def available() -> bool:
    return shutil.which(ffmpeg_bin()) is not None and shutil.which(ffprobe_bin()) is not None


def run(args: list[str], *, timeout: float | None = 1800) -> None:
    """ffmpeg -y -hide_banner -loglevel error <args>. В исключении — только хвост stderr."""
    cmd = [ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-nostdin", *args]
    _log.debug("ffmpeg.run", argc=len(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise FFmpegError(f"ffmpeg failed (code {proc.returncode}): {tail[-500:]}", tail)


def probe_json(path: Path) -> dict:
    cmd = [
        ffprobe_bin(),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe failed for {path.name}: {proc.stderr.strip()[-300:]}")
    return json.loads(proc.stdout)


def list_encoders() -> str:
    proc = subprocess.run(
        [ffmpeg_bin(), "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return proc.stdout


def list_filters() -> str:
    proc = subprocess.run(
        [ffmpeg_bin(), "-hide_banner", "-filters"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return proc.stdout


@dataclass(frozen=True)
class Size:
    w: int
    h: int

    @property
    def arg(self) -> str:
        return f"{self.w}x{self.h}"


def escape_filter_path(path: Path) -> str:
    """Путь для filtergraph (ass=, subtitles=): экранируем \\ : ' ,."""
    s = str(path)
    for ch in ("\\", ":", "'", ","):
        s = s.replace(ch, "\\" + ch)
    return s
