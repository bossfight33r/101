from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol


class PublishError(RuntimeError):
    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class VideoPublisher(Protocol):
    name: str

    def upload(
        self,
        file: Path,
        *,
        title: str,
        description: str,
        tags: list[str],
        language: str,
        publish_at: datetime,
    ) -> str:
        """Загрузить как private с publishAt. Вернуть id видео."""
        ...

    def set_thumbnail(self, video_id: str, image: Path) -> None: ...

    def upload_captions(self, video_id: str, srt: Path, language: str, name: str) -> None: ...
