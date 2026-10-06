"""Фоновая музыка (только треки Босса из конфига) с ducking под голос + loudnorm."""

from __future__ import annotations

import hashlib
from pathlib import Path

LOUDNORM = "loudnorm=I=-14:TP=-1.0:LRA=11"


def pick_track(tracks: list[str], video_id: str, resolve) -> Path | None:
    existing = [resolve(t) for t in tracks]
    existing = [p for p in existing if p.exists()]
    if not existing:
        return None
    idx = int(hashlib.sha256(video_id.encode()).hexdigest(), 16) % len(existing)
    return existing[idx]


def audio_filter(has_music: bool, volume: float) -> str:
    """filter_complex для [0:a] голос (+ [1:a] музыка) → [aout]."""
    if not has_music:
        return f"[0:a]{LOUDNORM}[aout]"
    return (
        "[0:a]asplit=2[voice][sc];"
        f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={volume}[m];"
        "[m][sc]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[duck];"
        f"[voice][duck]amix=inputs=2:duration=first:normalize=0,{LOUDNORM}[aout]"
    )


def music_inputs(track: Path | None) -> list[str]:
    return ["-stream_loop", "-1", "-i", str(track)] if track else []
