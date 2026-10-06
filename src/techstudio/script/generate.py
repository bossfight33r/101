"""Генерация сценария через LLM → Pydantic-валидация (с одной попыткой самоисправления)."""

from __future__ import annotations

import json

from pydantic import TypeAdapter, ValidationError

from techstudio.config import ROOT
from techstudio.core.llm import LLMError, extract_json
from techstudio.prompts import load as load_prompt
from techstudio.schemas import Channel, Scene, Script, Topic

_SCENE = TypeAdapter(Scene)


class ScriptGenerationError(RuntimeError):
    pass


def script_format_doc() -> str:
    path = ROOT / "docs" / "studio" / "script-format.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _payload(topic: Topic, channel: Channel, video_id: str) -> dict:
    return {
        "video_id": video_id,
        "topic": topic.model_dump(mode="json"),
        "channel": {
            "name": channel.name,
            "language": channel.language,
            "words_per_minute": channel.words_per_minute,
            "longform_sec": [channel.longform.min_sec, channel.longform.max_sec],
            "short_candidates": [channel.short_candidates_min, channel.short_candidates_max],
        },
    }


def system_prompt(channel: Channel) -> str:
    return (
        load_prompt("script.md")
        .replace("{min_sec}", str(channel.longform.min_sec))
        .replace("{max_sec}", str(channel.longform.max_sec))
        .replace("{wpm}", str(channel.words_per_minute))
        .replace("{script_format}", script_format_doc())
    )


def user_message(payload: dict, extra: str = "") -> str:
    text = (
        "Тема и параметры канала:\n```json\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n```"
    )
    return text + ("\n\n" + extra if extra else "")


def _to_script(data, topic: Topic, video_id: str, version: int) -> Script:
    if not isinstance(data, dict):
        raise ValueError("ожидался JSON-объект")
    data = {**data, "video_id": video_id, "topic_id": topic.id, "version": version}
    return Script.model_validate(data)


def generate_script(llm, topic: Topic, channel: Channel, video_id: str, version: int = 1) -> Script:
    payload = _payload(topic, channel, video_id)
    system = system_prompt(channel)
    text = llm.complete(task="script", system=system, user=user_message(payload))
    try:
        return _to_script(extract_json(text), topic, video_id, version)
    except (ValidationError, ValueError, LLMError) as first:
        repair = (
            "Предыдущий ответ не прошёл валидацию:\n"
            + str(first)[:3000]
            + "\n\nПредыдущий ответ:\n"
            + text[:20000]
            + "\n\nИсправь и верни полный JSON сценария."
        )
        text2 = llm.complete(
            task="script_repair", system=system, user=user_message(payload, repair)
        )
        try:
            return _to_script(extract_json(text2), topic, video_id, version)
        except (ValidationError, ValueError, LLMError) as e:
            raise ScriptGenerationError(f"LLM не выдал валидный сценарий: {e}") from e


def regenerate_scene(
    llm, script: Script, scene_id: str, topic: Topic, channel: Channel, note: str = ""
) -> Script:
    """Перегенерировать сцену N. Возвращает новую версию сценария (version+1)."""
    old = script.scene(scene_id)
    system = load_prompt("scene.md").replace("{script_format}", script_format_doc())
    payload = _payload(topic, channel, script.video_id)
    payload["script_outline"] = [
        {"id": s.id, "type": s.type, "narration": s.narration[:200]} for s in script.scenes
    ]
    payload["scene"] = old.model_dump(mode="json", exclude_none=True)
    extra = f"Перепиши сцену `{scene_id}`." + (f" Пожелание Босса: {note}" if note else "")
    text = llm.complete(task="scene", system=system, user=user_message(payload, extra))
    try:
        data = extract_json(text)
        if not isinstance(data, dict):
            raise ValueError("ожидался JSON-объект сцены")
        new_scene = _SCENE.validate_python({**data, "id": scene_id})
    except (ValidationError, ValueError, LLMError) as e:
        raise ScriptGenerationError(f"LLM не выдал валидную сцену: {e}") from e
    scenes = [new_scene if s.id == scene_id else s for s in script.scenes]
    return script.model_copy(update={"scenes": scenes, "version": script.version + 1})
