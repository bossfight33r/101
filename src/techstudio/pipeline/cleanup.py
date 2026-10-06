"""Очистка промежуточных файлов вышедших видео: сегменты, сырые визуалы, рабочие папки VHS, превью.
Остаются: long.mp4, шортсы, миниатюры, субтитры, сценарии, озвучка, манифесты."""

from __future__ import annotations

import shutil
from pathlib import Path

from techstudio.schemas import VideoStatus
from techstudio.services import Services

SCENE_PATTERNS = (
    "segment_*.mp4",
    "visual_*.mp4",
    "*_card.mp4",
    "*_card.png",
    "short_hook_9x16.mp4",
    "endcard_9x16.mp4",
)
SCENE_DIRS = ("vhs_*", "frames_*")
VIDEO_FILES = ("preview.mp4", "long_raw.mp4")


def _targets(vdir: Path) -> list[Path]:
    out: list[Path] = []
    for scene in (vdir / "scenes").glob("*"):
        for pat in SCENE_PATTERNS:
            out += [p for p in scene.glob(pat) if p.is_file()]
        for pat in SCENE_DIRS:
            out += [p for p in scene.glob(pat) if p.is_dir()]
    out += [vdir / f for f in VIDEO_FILES if (vdir / f).exists()]
    return out


def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def cleanup(
    svc: Services, *, dry_run: bool = True, statuses=(VideoStatus.published,)
) -> tuple[int, int]:
    """Возвращает (число объектов, байт). dry_run — только посчитать."""
    count = total = 0
    for rec in svc.db.list_videos():
        if rec.status not in statuses:
            continue
        for p in _targets(svc.video_dir(rec.id)):
            total += _size(p)
            count += 1
            if not dry_run:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
    return count, total
