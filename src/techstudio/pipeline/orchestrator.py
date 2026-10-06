"""Оркестратор видео. Рендер возможен только для одобренной версии сценария — проверка здесь."""

from __future__ import annotations

from techstudio.pipeline import scripts
from techstudio.schemas import Script, VideoStatus
from techstudio.services import Services

RENDERABLE = {
    VideoStatus.approved,
    VideoStatus.voicing,
    VideoStatus.rendering,
    VideoStatus.assembling,
    VideoStatus.failed,
    VideoStatus.final_review,
}


class NotApprovedError(RuntimeError):
    pass


def ensure_renderable(svc: Services, video_id: str) -> Script:
    rec = svc.db.require_video(video_id)
    if rec.status not in RENDERABLE:
        raise NotApprovedError(
            f"рендер из статуса {rec.status.value} невозможен: сначала approve сценария"
        )
    if rec.approved_version is None or rec.approved_version != rec.script_version:
        raise NotApprovedError("текущая версия сценария не одобрена (studio script approve)")
    info = scripts.approved_info(svc, video_id)
    script = scripts.load_script(svc, video_id)
    if (
        info is None
        or info.get("version") != script.version
        or info.get("sha256") != scripts.canonical_hash(script)
    ):
        raise NotApprovedError(
            "script.yaml отличается от одобренной версии — нужен повторный approve"
        )
    report = scripts.validate(svc, script)
    if not report.ok:
        raise NotApprovedError(
            "сценарий перестал проходить валидацию/policy:\n" + "\n".join(map(str, report.errors))
        )
    return script
