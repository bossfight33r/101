"""Манифест этапов: кеш по хешу входов + stage_version + хешам выходов (не по exists())."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inputs_hash(*parts: object) -> str:
    """Стабильный хеш входов: pydantic-модели, dict, строки, пути (по содержимому)."""
    h = hashlib.sha256()
    for part in parts:
        if isinstance(part, BaseModel):
            data = part.model_dump_json()
        elif isinstance(part, Path):
            data = file_hash(part) if part.exists() else f"missing:{part}"
        else:
            data = json.dumps(part, sort_keys=True, ensure_ascii=False, default=str)
        h.update(data.encode())
        h.update(b"\x00")
    return h.hexdigest()


class StageRecord(BaseModel):
    stage_version: int
    inputs_hash: str
    outputs: dict[str, str] = Field(default_factory=dict)  # имя -> sha256
    extra: dict = Field(default_factory=dict)
    finished_at: datetime


class Manifest(BaseModel):
    stages: dict[str, StageRecord] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Manifest:
        if path.exists():
            return cls.model_validate_json(path.read_text(encoding="utf-8"))
        return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)

    def is_fresh(self, stage: str, version: int, ihash: str, base: Path) -> bool:
        rec = self.stages.get(stage)
        if rec is None or rec.stage_version != version or rec.inputs_hash != ihash:
            return False
        for rel, digest in rec.outputs.items():
            p = base / rel
            if not p.exists() or file_hash(p) != digest:
                return False
        return True

    def record(
        self,
        stage: str,
        version: int,
        ihash: str,
        base: Path,
        outputs: list[Path],
        extra: dict | None = None,
    ) -> StageRecord:
        rec = StageRecord(
            stage_version=version,
            inputs_hash=ihash,
            outputs={p.relative_to(base).as_posix(): file_hash(p) for p in outputs},
            extra=extra or {},
            finished_at=datetime.now(UTC),
        )
        self.stages[stage] = rec
        return rec

    def invalidate(self, stage: str) -> None:
        self.stages.pop(stage, None)
