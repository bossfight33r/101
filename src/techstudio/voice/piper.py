"""Piper TTS (локально, CPU): `piper --model X.onnx --output_file out.wav`, текст в stdin."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from techstudio.config import VoiceConfig
from techstudio.voice.base import TTSError


def resolve_bin(binary: str) -> str:
    """`piper` из PATH, иначе из того же venv, что и интерпретатор (venv без activate)."""
    if shutil.which(binary):
        return binary
    sibling = Path(sys.executable).parent / binary
    return str(sibling) if sibling.exists() else binary


class PiperTTS:
    name = "piper"

    def __init__(self, binary: str = "piper", timeout: int = 600):
        self.binary = resolve_bin(binary)
        self.timeout = timeout

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def build_cmd(self, voice: VoiceConfig, out: Path) -> list[str]:
        cmd = [
            self.binary,
            "--model",
            voice.model,
            "--output_file",
            str(out),
            "--length_scale",
            str(voice.length_scale),
            "--sentence_silence",
            str(voice.sentence_silence),
        ]
        if voice.speaker is not None:
            cmd += ["--speaker", str(voice.speaker)]
        return cmd

    def synthesize(self, text: str, voice: VoiceConfig, out: Path) -> Path:
        if not Path(voice.model).exists():
            raise TTSError(f"нет модели голоса {voice.model} (см. runbook#piper)")
        out.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            self.build_cmd(voice, out),
            input=text,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        if proc.returncode != 0 or not out.exists():
            raise TTSError(f"piper failed: {proc.stderr.strip()[-300:]}")
        return out
