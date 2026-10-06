"""Детерминированный «LLM» для тестов и режима TS_LLM_PROVIDER=fake: сценарий из темы."""

from __future__ import annotations

import json
import re

from techstudio.sandbox.policy import NETWORK_TOOLS

_JSON_BLOCK = re.compile(r"```json\s*(.*?)```", re.S)


def _payload(user: str) -> dict:
    m = _JSON_BLOCK.search(user)
    return json.loads(m.group(1)) if m else {}


def fake_script(payload: dict) -> dict:
    topic = payload["topic"]
    ch = payload["channel"]
    tid = topic["id"]
    commands = topic.get("must_show_commands") or ["uname -a"]
    scenes: list[dict] = [
        {
            "id": "plan",
            "type": "slide",
            "chapter": "План",
            "title": topic["title"][:60],
            "bullets": (topic.get("key_points") or ["Разберём по шагам"])[:4],
            "narration": "Сначала коротко план. Три шага, каждый проверим руками.",
        }
    ]
    for i, cmd in enumerate(commands, 1):
        needs_net = bool(NETWORK_TOOLS.search(cmd))
        scene = {
            "id": f"cmd{i}",
            "type": "terminal",
            "chapter": f"Шаг {i}",
            "commands": [cmd],
            "narration": f"Набираем команду номер {i}. Смотри на вывод: это реальный результат, а не картинка.",
            "short_candidate": True,
            "short_hook": f"Одна команда, которая экономит время: шаг {i}.",
        }
        if needs_net:
            scene.update(mode="replay", replay_output_key=f"assets/replay/{tid}/cmd{i}")
        elif m := re.match(r"python3?\s+(\S+\.py)\b", cmd):
            scene["files"] = {m.group(1): "code"}  # запускаем код из code-сцены
        scenes.append(scene)
    scenes += [
        {
            "id": "code",
            "type": "code",
            "chapter": "Автоматизация",
            "language": "python",
            "reveal": "by_line",
            "highlight_lines": [3],
            "code": "import subprocess\n\nout = subprocess.run(['uname', '-a'], capture_output=True, text=True)\nprint(out.stdout)\n",
            "narration": "Это же можно сделать из Python. Третья строка запускает команду и забирает вывод.",
            "short_candidate": True,
            "short_hook": "Как запустить команду из Python и забрать вывод.",
        },
        {
            "id": "scheme",
            "type": "diagram",
            "chapter": "Как это устроено",
            "mermaid": "flowchart LR\n  A[Ноутбук] --> B[Роутер]\n  B --> C((Интернет))\n",
            "narration": "Схема простая: ноутбук ходит в интернет через роутер.",
            "short_candidate": True,
            "short_hook": "Схема домашней сети за десять секунд.",
        },
        {
            "id": "summary",
            "type": "slide",
            "chapter": "Итоги",
            "title": "Итоги",
            "bullets": ["Команды проверены", "Скрипт готов", "Схема понятна"],
            "narration": "По шагам: команды проверили, скрипт написали, схему поняли.",
        },
    ]
    # добиваем длительность через min_sec не-шортсовых сцен, чтобы попасть в окно канала
    wpm = ch["words_per_minute"]
    speech = {s["id"]: len(s["narration"].split()) * 60 / wpm + 0.8 for s in scenes}
    target = ch["longform_sec"][0] * 1.1 - 6
    fillers = [s for s in scenes if not s.get("short_candidate")]
    extra = max(target - sum(speech.values()), 0) / len(fillers)
    for s in scenes:
        pad = extra if s in fillers else 4.0
        s["min_sec"] = round(speech[s["id"]] + pad, 1)
    return {
        "title": topic["title"][:100],
        "hook": "Через пару минут ты сделаешь это сам и проверишь результат.",
        "outro": "Попробуй на своём железе и напиши в комментариях, что получилось.",
        "scenes": scenes,
    }


def script_responder(system: str, user: str) -> str:
    return json.dumps(fake_script(_payload(user)), ensure_ascii=False)


def scene_responder(system: str, user: str) -> str:
    p = _payload(user)
    scene = dict(p["scene"])
    scene["narration"] = scene["narration"] + " Переписано короче."
    return json.dumps(scene, ensure_ascii=False)


def metadata_responder(system: str, user: str) -> str:
    p = _payload(user)
    title = p.get("title", "Видео")
    return json.dumps(
        {
            "title": title[:100],
            "description": f"{title}. Пошагово, с реальными командами и выводом.",
            "tags": ["linux", "сети"],
            "thumbnail_texts": ["СДЕЛАЙ САМ", "ЗА 5 МИНУТ", "БЕЗ ОШИБОК"],
        },
        ensure_ascii=False,
    )


def topics_responder(system: str, user: str) -> str:
    return json.dumps(
        {
            "topics": [
                {
                    "id": "wireguard-openwrt",
                    "title": "WireGuard на OpenWrt за 10 минут",
                    "audience_level": "intermediate",
                    "key_points": ["пакеты", "ключи", "пир"],
                    "must_show_commands": ["wg show"],
                    "notes": "по аналитике: терминальные сцены удерживают лучше",
                }
            ]
        },
        ensure_ascii=False,
    )


def default_responses() -> dict:
    return {
        "script": script_responder,
        "script_repair": script_responder,
        "scene": scene_responder,
        "metadata": metadata_responder,
        "topics": topics_responder,
    }
