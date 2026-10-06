"""Локальное хранилище по ключам: key — относительный путь от корня data/studio."""

from __future__ import annotations

import shutil
from pathlib import Path


class LocalStorage:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in (p, *p.parents):
            raise ValueError(f"ключ вне хранилища: {key}")
        return p

    def key(self, path: Path) -> str:
        return Path(path).resolve().relative_to(self.root.resolve()).as_posix()

    def exists(self, key: str) -> bool:
        return self.path(key).exists()

    def ensure_dir(self, key: str) -> Path:
        p = self.path(key)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def write_text(self, key: str, text: str) -> Path:
        p = self.path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(p)
        return p

    def read_text(self, key: str) -> str:
        return self.path(key).read_text(encoding="utf-8")

    def put_file(self, src: Path, key: str) -> Path:
        p = self.path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, p)
        return p
