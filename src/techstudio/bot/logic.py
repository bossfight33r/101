"""Логика раздела TechStudio в боте без зависимости от Telegram: на вход — команда/кнопка/файл,
на выход — список Reply (+ долгая задача job, которую адаптер выполняет в потоке)."""

from __future__ import annotations

import html
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from techstudio.pipeline import orchestrator, publish, review, scripts
from techstudio.render.fake import has_fake
from techstudio.schemas import VideoStatus
from techstudio.script.io import ScriptParseError
from techstudio.services import Services

PREFIX = "ts"


@dataclass
class Reply:
    text: str = ""
    buttons: list[list[tuple[str, str]]] = field(default_factory=list)  # [[(label, callback_data)]]
    documents: list[Path] = field(default_factory=list)
    videos: list[Path] = field(default_factory=list)
    photos: list[Path] = field(default_factory=list)
    html: bool = False  # True — text в HTML, всё динамическое уже экранировано esc()


Job = Callable[..., list[Reply]]  # job(progress=None); progress(str) — обновить статус-сообщение


def is_admin(svc: Services, user_id: int | None) -> bool:
    return user_id is not None and user_id in svc.settings.admin_id_set


def cb(action: str, video_id: str, arg: str | int | None = None) -> str:
    data = f"{PREFIX}:{action}:{video_id}" + (f":{arg}" if arg is not None else "")
    if len(data.encode()) > 64:
        raise ValueError(f"callback_data > 64 байт: {data}")
    return data


def esc(value) -> str:
    """Экранирование для parse_mode=HTML: в командах и текстах бывают <YOUR_KEY>, >, &&."""
    return html.escape(str(value), quote=False)


def _flag(scene) -> str:
    if scene.type != "terminal":
        return ""
    marks = ["REPLAY" if scene.mode == "replay" else "live"]
    if scene.network:
        marks.append("⚠️NETWORK")
    return " [" + ", ".join(marks) + "]"


# ---------------- гейт 1: сценарий ----------------


def script_gate(svc: Services, video_id: str) -> list[Reply]:
    script = scripts.load_script(svc, video_id)
    report = scripts.validate(svc, script)
    lines = [
        f"📝 <b>Сценарий</b> {esc(video_id)} v{script.version}",
        f"<b>{esc(script.title)}</b>",
        f"Хук: {esc(script.hook)}",
        f"≈ {report.estimated_sec / 60:.1f} мин, сцен: {len(script.scenes)}, шортсов: {sum(s.short_candidate for s in script.scenes)}",
        "",
    ]
    for i, s in enumerate(script.scenes, 1):
        extra = " 🎬" if s.short_candidate else ""
        lines.append(
            f"{i}. {s.type} <code>{esc(s.id)}</code>{_flag(s)}{extra}: {esc(s.narration[:90])}"
        )
        if s.type == "terminal":
            lines.append("   <code>$ " + esc(" ; ".join(s.commands)[:150]) + "</code>")
            if s.files:
                lines.append("   файлы: " + esc(", ".join(f"{k}←{v}" for k, v in s.files.items())))
    if report.issues:
        lines += ["", "<b>Проблемы:</b>"] + [f"• {esc(i)}" for i in report.issues[:15]]
    buttons = []
    if report.ok:
        buttons.append([("✅ Approve и рендер", cb("ok", video_id))])
    buttons.append(
        [
            ("✏️ Прислать правку (YAML)", cb("ed", video_id)),
            ("🔁 Перегенерировать сцену", cb("rgm", video_id)),
        ]
    )
    return [
        Reply(
            text="\n".join(lines),
            buttons=buttons,
            documents=[scripts.script_path(svc, video_id)],
            html=True,
        )
    ]


def scene_picker(
    svc: Services, video_id: str, action: str, include_service: bool = False
) -> list[Reply]:
    script = scripts.load_script(svc, video_id)
    ids = ["hook"] if include_service else []
    ids += [s.id for s in script.scenes] + (
        ["outro"] if include_service and script.outro.strip() else []
    )
    rows, row = [], []
    for i, sid in enumerate(ids):
        row.append((f"{i}. {sid}", cb(action, video_id, i)))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return [Reply(text="Какую сцену?", buttons=rows)]


def _scene_by_index(svc: Services, video_id: str, idx: int, include_service: bool) -> str:
    script = scripts.load_script(svc, video_id)
    ids = ["hook"] if include_service else []
    ids += [s.id for s in script.scenes] + (
        ["outro"] if include_service and script.outro.strip() else []
    )
    return ids[idx]


# ---------------- гейт 2: финал ----------------


def final_gate(svc: Services, video_id: str) -> list[Reply]:
    summary = orchestrator.final_summary(svc, video_id)
    rec = svc.db.require_video(video_id)
    if summary is None:
        return [Reply(text=f"{video_id}: нет результата рендера")]
    long = summary["long"]
    lines = [
        f"🎬 <b>Финал</b> {esc(video_id)}",
        f"<b>{esc(summary['meta']['title'])}</b>",
        f"Длительность {long['duration'] / 60:.1f} мин, глав {len(long['chapters'])}"
        + ("" if long["chapters_valid"] else " (⚠️ главы невалидны)"),
        f"Шортсов: {len(summary['shorts'])}",
    ]
    if summary["flags"]:
        lines.append(
            "Флаги: "
            + ", ".join(
                f"{esc(f['scene_id'])}={'REPLAY' if f['mode'] == 'replay' else 'NETWORK'}"
                for f in summary["flags"]
            )
        )
    if summary["warnings"]:
        lines += ["", "<b>Предупреждения:</b>"] + [f"• {esc(w)}" for w in summary["warnings"][:15]]
    lines.append("")
    lines.append(f"Миниатюра: {rec.thumbnail_id or 'не выбрана'}")
    thumbs = summary["thumbnails"]
    thumb_row = [
        (
            (("✓ " if rec.thumbnail_id == t["id"] else "") + f"🖼 {t['id']}"),
            cb("th", video_id, t["id"]),
        )
        for t in thumbs
    ]
    buttons = [thumb_row]
    fake = has_fake(summary["warnings"]) and not svc.settings.allow_fake_publish
    if fake:
        lines.append("⛔ Есть fake-визуалы — публикация недоступна, нужен перерендер с Docker.")
    elif rec.thumbnail_id:
        buttons.append([("✅ Approve и публикация", cb("fa", video_id))])
    buttons.append(
        [("❌ Reject", cb("fr", video_id)), ("🔁 Перерендер сцены", cb("rrm", video_id))]
    )
    return [
        Reply(videos=[svc.storage.path(summary["preview_key"])], text=f"Превью: {video_id}"),
        *(
            Reply(
                videos=[svc.storage.path(s["video_key"])],
                text=f"Шортс {s['id']} ({s['duration']:.0f} с)",
            )
            for s in summary["shorts"]
        ),
        Reply(photos=[svc.storage.path(t["image_key"]) for t in thumbs]),
        Reply(text="\n".join(lines), buttons=buttons, html=True),
    ]


# ---------------- действия ----------------


def _render_job(svc: Services, video_id: str, scene_id: str | None = None) -> Job:
    def job(progress=None) -> list[Reply]:
        try:
            if scene_id:
                orchestrator.rerender_scene(svc, video_id, scene_id, progress=progress)
            else:
                orchestrator.render_video(svc, video_id, progress=progress)
        except Exception as e:  # noqa: BLE001 — сообщаем Боссу
            return [
                Reply(
                    text=f"❌ Рендер {video_id} упал: {type(e).__name__}: {str(e)[:300]}\n/retry {video_id}"
                )
            ]
        return final_gate(svc, video_id)

    return job


def handle_callback(svc: Services, data: str) -> tuple[list[Reply], Job | None]:
    parts = data.split(":")
    if len(parts) < 3 or parts[0] != PREFIX:
        return [], None
    action, vid = parts[1], parts[2]
    arg = parts[3] if len(parts) > 3 else None
    try:
        if action == "ok":
            scripts.approve(svc, vid)
            return [Reply(text=f"✅ Сценарий {vid} одобрен. Рендерю…")], _render_job(svc, vid)
        if action == "ed":
            return [
                Reply(text="Пришли исправленный script.yaml файлом (video_id внутри не меняй).")
            ], None
        if action == "rgm":
            return scene_picker(svc, vid, "rg"), None
        if action == "rg":
            sid = _scene_by_index(svc, vid, int(arg), False)
            scripts.regenerate_scene(svc, vid, sid)
            return [Reply(text=f"🔁 Сцена {sid} переписана."), *script_gate(svc, vid)], None
        if action == "th":
            review.choose_thumbnail(svc, vid, arg)
            return final_gate(svc, vid)[-1:], None
        if action == "fa":
            review.approve(svc, vid)
            return [Reply(text=f"✅ {vid} одобрено. Загружаю…")], _publish_job(svc, vid)
        if action == "fr":
            review.reject(svc, vid, "бот")
            return [Reply(text=f"❌ {vid} отклонено. Можно прислать правку сценария.")], None
        if action == "rrm":
            return scene_picker(svc, vid, "rr", include_service=True), None
        if action == "rr":
            sid = _scene_by_index(svc, vid, int(arg), True)
            return [Reply(text=f"🔁 Перерендер сцены {sid}…")], _render_job(svc, vid, sid)
    except Exception as e:  # noqa: BLE001
        return [Reply(text=f"⚠️ {type(e).__name__}: {str(e)[:500]}")], None
    return [Reply(text=f"неизвестное действие {action}")], None


def _publish_job(svc: Services, video_id: str) -> Job:
    def job(progress=None) -> list[Reply]:  # noqa: ARG001
        try:
            pubs = publish.publish_video(svc, video_id)
        except Exception as e:  # noqa: BLE001
            return [
                Reply(
                    text=f"❌ Публикация {video_id}: {type(e).__name__}: {str(e)[:300]}\nПовтор: /publish {video_id}"
                )
            ]
        lines = [f"📅 {video_id} запланировано:"]
        for p in pubs:
            lines.append(
                f"• {p.kind} {p.short_id or ''} {p.scheduled_at:%Y-%m-%d %H:%M} UTC {p.url or ''}"
            )
            lines += [f"  ⚠️ {n}" for n in p.notes]
        return [Reply(text="\n".join(lines))]

    return job


def handle_document(svc: Services, filename: str, text: str) -> list[Reply]:
    if not filename.endswith((".yaml", ".yml")):
        return [Reply(text="Жду script.yaml")]
    try:
        import yaml

        vid = (yaml.safe_load(text) or {}).get("video_id")
        if not vid:
            return [Reply(text="В файле нет video_id")]
        script, report = scripts.import_script(svc, vid, text)
    except ScriptParseError as e:
        return [Reply(text=f"⚠️ {str(e)[:1500]}")]
    except Exception as e:  # noqa: BLE001
        return [Reply(text=f"⚠️ {type(e).__name__}: {str(e)[:500]}")]
    return [Reply(text=f"📥 Правка принята: v{script.version}"), *script_gate(svc, vid)]


def handle_command(svc: Services, command: str, args: list[str]) -> tuple[list[Reply], Job | None]:
    try:
        if command == "studio":
            waiting = [
                v
                for v in svc.db.list_videos()
                if v.status
                in (VideoStatus.script_review, VideoStatus.final_review, VideoStatus.failed)
            ]
            if not waiting:
                return [Reply(text="TechStudio: ничего не ждёт ревью.")], None
            lines = ["TechStudio, ждут тебя:"] + [f"• {v.id} — {v.status.value}" for v in waiting]
            lines.append("/review VIDEO_ID — открыть")
            return [Reply(text="\n".join(lines))], None
        if command == "topics":
            from techstudio.schemas import TopicStatus

            ts = svc.db.list_topics(TopicStatus.backlog)
            return [
                Reply(
                    text="Бэклог:\n" + "\n".join(f"• {t.id} — {t.title}" for t in ts)
                    if ts
                    else "Бэклог пуст"
                )
            ], None
        if not args:
            return [Reply(text=f"/{command} VIDEO_ID")], None
        target = args[0]
        if command == "new":

            def job(progress=None) -> list[Reply]:  # noqa: ARG001
                try:
                    script, _ = scripts.new_script(svc, target)
                except Exception as e:  # noqa: BLE001
                    return [Reply(text=f"⚠️ {type(e).__name__}: {str(e)[:500]}")]
                return script_gate(svc, script.video_id)

            return [Reply(text=f"Пишу сценарий по теме {target}…")], job
        if command == "review":
            rec = svc.db.require_video(target)
            if rec.status == VideoStatus.final_review:
                return final_gate(svc, target), None
            return script_gate(svc, target), None
        if command == "regen":
            if len(args) < 2:
                return [Reply(text="/regen VIDEO_ID SCENE_ID пожелание")], None
            note = " ".join(args[2:])
            scripts.regenerate_scene(svc, target, args[1], note)
            return [Reply(text=f"🔁 Сцена {args[1]} переписана."), *script_gate(svc, target)], None
        if command == "status":
            rec = svc.db.require_video(target)
            text = f"{rec.id}: {rec.status.value}, сценарий v{rec.script_version}"
            if rec.failure:
                text += f"\nошибка: {rec.failure.stage}: {rec.failure.message[:300]}"
            return [Reply(text=text)], None
        if command == "retry":
            return [Reply(text=f"Повторяю {target}…")], _retry_job(svc, target)
        if command == "publish":
            return [Reply(text=f"Публикую {target}…")], _publish_job(svc, target)
    except Exception as e:  # noqa: BLE001
        return [Reply(text=f"⚠️ {type(e).__name__}: {str(e)[:500]}")], None
    return [
        Reply(
            text="Команды: /studio /topics /new TOPIC /review VID /regen VID SCENE пожелание /status VID /retry VID /publish VID"
        )
    ], None


def _retry_job(svc: Services, video_id: str) -> Job:
    def job(progress=None) -> list[Reply]:
        try:
            orchestrator.retry(svc, video_id, progress=progress)
        except Exception as e:  # noqa: BLE001
            return [Reply(text=f"❌ retry {video_id}: {type(e).__name__}: {str(e)[:300]}")]
        return final_gate(svc, video_id)

    return job
