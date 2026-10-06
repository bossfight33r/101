"""Предложения новых тем: LLM по отчёту → файл для ручного ревью. В бэклог — только после accept."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import ValidationError

from techstudio.core.llm import extract_json
from techstudio.schemas import Topic, TopicStatus

SYSTEM = """Ты помогаешь планировать обучающий YouTube-канал про сети, роутеры, прошивки, Linux и Python-автоматизацию.
По отчёту аналитики и списку существующих тем предложи 5 новых тем, которые дадут зрителю практическую пользу.
Не повторяй существующие. Верни ТОЛЬКО JSON: {"topics": [{"id": "kebab-case", "title": "...", "audience_level": "beginner|intermediate|advanced",
"key_points": [...], "must_show_commands": [...], "notes": "почему эта тема — со ссылкой на данные отчёта"}]}"""


def suggest(svc, report: dict) -> Path:
    existing = [t.id for t in svc.db.list_topics()]
    payload = {"report": report, "existing_topic_ids": existing}
    text = svc.llm.complete(
        task="topics",
        system=SYSTEM,
        user="```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```",
    )
    data = extract_json(text)
    items = data.get("topics", []) if isinstance(data, dict) else data
    topics, rejected = [], []
    for item in items:
        try:
            t = Topic.model_validate({**item, "status": TopicStatus.backlog})
        except ValidationError as e:
            rejected.append(f"{item.get('id', '?')}: {e.errors()[0]['msg']}")
            continue
        if t.id not in existing:
            topics.append(t)
    path = svc.storage.path(f"topics/suggestions-{datetime.now(UTC):%Y%m%d-%H%M%S}.yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"topics": [t.model_dump(mode="json") for t in topics]}
    header = "# Предложенные темы — ревью вручную.\n# Принять: studio topic accept <этот файл> <id> (или --all)\n"
    if rejected:
        header += "".join(f"# отброшено: {r}\n" for r in rejected)
    path.write_text(
        header + yaml.safe_dump(body, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return path


def accept(svc, path: Path, topic_ids: list[str], accept_all: bool = False) -> list[str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    added = []
    for item in data.get("topics", []):
        t = Topic.model_validate(item)
        if (accept_all or t.id in topic_ids) and svc.db.get_topic(t.id) is None:
            svc.db.upsert_topic(t)
            added.append(t.id)
    return added
