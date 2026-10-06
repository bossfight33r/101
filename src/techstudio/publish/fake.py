"""Фейковый YouTube: записывает вызовы. Можно заставить падать миниатюру."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from techstudio.publish.base import PublishError


class FakePublisher:
    name = "fake"

    def __init__(self, fail_thumbnail: bool = False):
        self.fail_thumbnail = fail_thumbnail
        self.uploads: list[dict] = []
        self.thumbnails: list[tuple[str, Path]] = []
        self.captions: list[tuple[str, Path, str]] = []

    def upload(
        self, file: Path, *, title, description, tags, language, publish_at: datetime
    ) -> str:
        vid = f"yt{len(self.uploads) + 1:04d}"
        self.uploads.append(
            dict(
                id=vid,
                file=Path(file),
                title=title,
                description=description,
                tags=tags,
                language=language,
                publish_at=publish_at,
            )
        )
        return vid

    def set_thumbnail(self, video_id: str, image: Path) -> None:
        if self.fail_thumbnail:
            raise PublishError("thumbnails.set: 403 канал не подтверждён", retryable=False)
        self.thumbnails.append((video_id, Path(image)))

    def upload_captions(self, video_id: str, srt: Path, language: str, name: str) -> None:
        self.captions.append((video_id, Path(srt), language))
