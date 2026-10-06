"""Docker-раннер песочницы: non-root, лимиты CPU/RAM/PID/времени, без сети по умолчанию,
read-only rootfs, cap-drop ALL. С хоста монтируется только рабочая папка сцены (/out)."""

from __future__ import annotations

import secrets
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from techstudio.core import log

_log = log.get("sandbox")

Runner = Callable[..., subprocess.CompletedProcess]


class SandboxError(RuntimeError):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class SandboxLimits:
    cpus: float = 1.0
    memory: str = "1g"
    pids: int = 256
    timeout: int = 300
    read_only: bool = (
        True  # rootfs только чтение (+ tmpfs /tmp и ~); выключить, если VHS/Chromium не стартует
    )


class DockerSandbox:
    def __init__(
        self,
        image: str = "techstudio-sandbox:latest",
        docker_bin: str = "docker",
        limits: SandboxLimits | None = None,
        runner: Runner | None = None,
    ):
        self.image = image
        self.docker_bin = docker_bin
        self.limits = limits or SandboxLimits()
        self._run = runner or subprocess.run

    def available(self) -> bool:
        if shutil.which(self.docker_bin) is None:
            return False
        try:
            proc = self._run(
                [self.docker_bin, "image", "inspect", self.image],
                capture_output=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0

    def build_args(self, workdir: Path, args: list[str], *, network: bool, name: str) -> list[str]:
        lim = self.limits
        return [
            self.docker_bin,
            "run",
            "--rm",
            "--name",
            name,
            "--network",
            "bridge" if network else "none",
            "--user",
            "1000:1000",
            "--cpus",
            str(lim.cpus),
            "--memory",
            lim.memory,
            "--memory-swap",
            lim.memory,
            "--pids-limit",
            str(lim.pids),
            *(["--read-only"] if lim.read_only else []),
            "--tmpfs",
            "/tmp:rw,size=256m",
            "--tmpfs",
            "/home/studio:rw,size=256m,uid=1000,gid=1000",
            "--shm-size",
            "512m",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "-v",
            f"{workdir.resolve()}:/out:rw",
            "-w",
            "/home/studio",
            self.image,
            *args,
        ]

    def run(
        self, workdir: Path, args: list[str], *, network: bool = False
    ) -> subprocess.CompletedProcess:
        name = f"ts-{secrets.token_hex(4)}"
        cmd = self.build_args(workdir, args, network=network, name=name)
        _log.info("sandbox.run", name=name, network=network, image=self.image)
        try:
            proc = self._run(
                cmd, capture_output=True, text=True, timeout=self.limits.timeout, check=False
            )
        except subprocess.TimeoutExpired as e:
            self._run([self.docker_bin, "kill", name], capture_output=True, timeout=30, check=False)
            raise SandboxError(f"песочница: превышен лимит времени {self.limits.timeout} с") from e
        if proc.returncode != 0:
            tail = (proc.stderr or "").strip()[-400:]
            raise SandboxError(f"песочница: код {proc.returncode}: {tail}", retryable=False)
        return proc
