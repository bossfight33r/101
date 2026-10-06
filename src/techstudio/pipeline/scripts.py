"""Жизненный цикл сценария: new → script_review → (export → правка → import)* → approve."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from techstudio.core import log
from techstudio.schemas import Script, TopicStatus, VideoStatus
from techstudio.script import generate, io
from techstudio.script.validate import ValidationReport, validate_script
from techstudio.services import Services

_log = log.get("scripts")

EDITABLE = {
    VideoStatus.draft,
    VideoStatus.script_review,
    VideoStatus.approved,
    VideoStatus.failed,
    VideoStatus.final_review,
    VideoStatus.rejected,  # после Reject можно прислать правку сценария
}


class ScriptStateError(RuntimeError):
    pass


def script_path(svc: Services, video_id: str) -> Path:
    return svc.video_dir(video_id) / "script.yaml"


def version_path(svc: Services, video_id: str, version: int) -> Path:
    return svc.video_dir(video_id) / "versions" / f"script.v{version}.yaml"


def load_script(svc: Services, video_id: str) -> Script:
    path = script_path(svc, video_id)
    if not path.exists():
        raise ScriptStateError(f"у видео {video_id} нет сценария")
    return io.load(path)


def canonical_hash(script: Script) -> str:
    return hashlib.sha256(script.model_dump_json().encode()).hexdigest()


def approved_info(svc: Services, video_id: str) -> dict | None:
    key = f"videos/{video_id}/approved.json"
    return json.loads(svc.storage.read_text(key)) if svc.storage.exists(key) else None


def _asset_exists(svc: Services):
    return lambda key: svc.storage.exists(key)


def validate(svc: Services, script: Script) -> ValidationReport:
    checker = (
        svc.overrides["mermaid_checker"]
        if "mermaid_checker" in svc.overrides
        else svc.mermaid_checker
    )
    return validate_script(
        script, svc.channel, mermaid_checker=checker, asset_exists=_asset_exists(svc)
    )


def review_header(script: Script, report: ValidationReport) -> str:
    flags = []
    for s in script.scenes:
        if s.type == "terminal":
            marks = [f"mode={s.mode}"] + (["NETWORK"] if s.network else [])
            flags.append(f"  {s.id}: {', '.join(marks)}: {' && '.join(s.commands)}")
    lines = [
        f"TechStudio сценарий {script.video_id} v{script.version}",
        f"Оценка длительности: {report.estimated_sec / 60:.1f} мин",
        "Терминальные сцены (флаги):",
        *(flags or ["  нет"]),
    ]
    if report.issues:
        lines.append("Проблемы:")
        lines += [f"  {i}" for i in report.issues]
    lines.append(
        "Правь ниже и присылай обратно (studio script import / бот). video_id и topic_id не менять."
    )
    return "\n".join(lines)


def _save_version(svc: Services, script: Script, report: ValidationReport) -> Path:
    header = review_header(script, report)
    io.save(script, version_path(svc, script.video_id, script.version), header)
    path = io.save(script, script_path(svc, script.video_id), header)
    svc.storage.write_text(
        f"videos/{script.video_id}/validation.json",
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
    )
    return path


def _drop_approval(svc: Services, video_id: str) -> None:
    svc.storage.path(f"videos/{video_id}/approved.json").unlink(missing_ok=True)


def _new_video_id(svc: Services, topic_id: str) -> str:
    base = f"v{datetime.now(UTC):%Y%m%d}-{topic_id}"[:36]  # callback_data бота ≤ 64 байт
    vid, n = base, 2
    while svc.db.get_video(vid):
        vid, n = f"{base}-{n}", n + 1
    return vid


def new_script(svc: Services, topic_id: str) -> tuple[Script, ValidationReport]:
    topic = svc.db.get_topic(topic_id)
    if topic is None:
        raise ScriptStateError(f"тема {topic_id} не найдена (studio topic add/import)")
    vid = _new_video_id(svc, topic_id)
    svc.db.create_video(vid, topic_id, svc.channel.id)
    script = generate.generate_script(svc.llm, topic, svc.channel, vid)
    report = validate(svc, script)
    _save_version(svc, script, report)
    svc.db.update_video(
        vid, status=VideoStatus.script_review, script_version=script.version, approved_version=None
    )
    svc.db.set_topic_status(topic_id, TopicStatus.in_progress)
    _log.info("script.new", video_id=vid, ok=report.ok, est_sec=round(report.estimated_sec))
    return script, report


def export_script(svc: Services, video_id: str, dest: Path | None = None) -> Path:
    path = script_path(svc, video_id)
    if not path.exists():
        raise ScriptStateError(f"у видео {video_id} нет сценария")
    if dest:
        dest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        return dest
    return path


def import_script(svc: Services, video_id: str, text: str) -> tuple[Script, ValidationReport]:
    """Правка Босса. Схема невалидна → ScriptParseError. Иначе version+1, approve сбрасывается."""
    rec = svc.db.require_video(video_id)
    if rec.status not in EDITABLE:
        raise ScriptStateError(f"видео в статусе {rec.status.value}: правка сценария недоступна")
    edited = io.from_yaml(text)
    if edited.video_id != video_id or edited.topic_id != rec.topic_id:
        raise ScriptStateError("video_id/topic_id в файле не совпадают с видео")
    script = edited.model_copy(update={"version": rec.script_version + 1})
    report = validate(svc, script)
    _save_version(svc, script, report)
    _drop_approval(svc, video_id)
    svc.db.update_video(
        video_id,
        status=VideoStatus.script_review,
        script_version=script.version,
        approved_version=None,
        final_approved=False,
    )
    svc.db.add_review_action(
        video_id, "script", "import", {"version": script.version, "ok": report.ok}
    )
    return script, report


def regenerate_scene(
    svc: Services, video_id: str, scene_id: str, note: str = ""
) -> tuple[Script, ValidationReport]:
    rec = svc.db.require_video(video_id)
    if rec.status not in EDITABLE:
        raise ScriptStateError(f"видео в статусе {rec.status.value}")
    current = load_script(svc, video_id)
    topic = svc.db.get_topic(rec.topic_id)
    script = generate.regenerate_scene(svc.llm, current, scene_id, topic, svc.channel, note)
    script = script.model_copy(update={"version": rec.script_version + 1})
    report = validate(svc, script)
    _save_version(svc, script, report)
    _drop_approval(svc, video_id)
    svc.db.update_video(
        video_id,
        status=VideoStatus.script_review,
        script_version=script.version,
        approved_version=None,
    )
    svc.db.add_review_action(
        video_id, "script", "regenerate_scene", {"scene_id": scene_id, "note": note}
    )
    return script, report


def approve(svc: Services, video_id: str) -> Script:
    rec = svc.db.require_video(video_id)
    if rec.status not in (VideoStatus.script_review, VideoStatus.approved):
        raise ScriptStateError(f"approve сценария из статуса {rec.status.value} невозможен")
    script = load_script(svc, video_id)
    saved = io.load(version_path(svc, video_id, rec.script_version))
    if script.version != rec.script_version or canonical_hash(script) != canonical_hash(saved):
        raise ScriptStateError("script.yaml изменён мимо import — сделай studio script import")
    report = validate(svc, script)
    if not report.ok:
        raise ScriptStateError(
            "сценарий не проходит валидацию:\n" + "\n".join(str(i) for i in report.errors)
        )
    svc.storage.write_text(
        f"videos/{video_id}/approved.json",
        json.dumps({"version": script.version, "sha256": canonical_hash(script)}),
    )
    svc.db.update_video(video_id, status=VideoStatus.approved, approved_version=script.version)
    svc.db.add_review_action(video_id, "script", "approve", {"version": script.version})
    return script
