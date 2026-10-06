from __future__ import annotations

from pathlib import Path

from techstudio.config import load_topics
from techstudio.core.db import Database
from techstudio.schemas import Topic, TopicStatus


def add(db: Database, topic: Topic, *, overwrite: bool = False) -> Topic:
    if db.get_topic(topic.id) and not overwrite:
        raise ValueError(f"тема {topic.id} уже есть (используй --overwrite)")
    db.upsert_topic(topic)
    return topic


def import_file(db: Database, path: Path, *, overwrite: bool = False) -> tuple[int, int]:
    """Импорт YAML. Возвращает (добавлено, пропущено)."""
    added = skipped = 0
    for topic in load_topics(path):
        if db.get_topic(topic.id) and not overwrite:
            skipped += 1
            continue
        db.upsert_topic(topic)
        added += 1
    return added, skipped


def list_topics(db: Database, status: TopicStatus | None = None) -> list[Topic]:
    return db.list_topics(status)
