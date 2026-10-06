"""Гейт 2 (финал): выбор миниатюры, approve / reject. Публикация — только после approve."""

from __future__ import annotations

from techstudio.pipeline import orchestrator
from techstudio.render.fake import has_fake
from techstudio.schemas import VideoStatus
from techstudio.services import Services


class ReviewError(RuntimeError):
    pass


def _summary(svc: Services, video_id: str) -> dict:
    s = orchestrator.final_summary(svc, video_id)
    if s is None:
        raise ReviewError("нет результата рендера — сначала studio render")
    return s


def choose_thumbnail(svc: Services, video_id: str, variant: str) -> None:
    ids = {t["id"] for t in _summary(svc, video_id)["thumbnails"]}
    if variant not in ids:
        raise ReviewError(f"нет миниатюры {variant} (есть: {', '.join(sorted(ids))})")
    svc.db.update_video(video_id, thumbnail_id=variant)
    svc.db.add_review_action(video_id, "final", "thumbnail", {"variant": variant})


def approve(svc: Services, video_id: str, thumbnail: str | None = None) -> None:
    rec = svc.db.require_video(video_id)
    if rec.status != VideoStatus.final_review:
        raise ReviewError(f"финальный approve из статуса {rec.status.value} невозможен")
    if thumbnail:
        choose_thumbnail(svc, video_id, thumbnail)
        rec = svc.db.require_video(video_id)
    if not rec.thumbnail_id:
        raise ReviewError("выбери миниатюру (A/B/C)")
    if has_fake(_summary(svc, video_id)["warnings"]) and not svc.settings.allow_fake_publish:
        raise ReviewError(
            "в видео фейковые визуалы (нет Docker-песочницы) — публиковать нельзя: "
            "TS_RENDERERS=real и studio render --scene …"
        )
    svc.db.update_video(video_id, final_approved=True)
    svc.db.add_review_action(video_id, "final", "approve", {"thumbnail": rec.thumbnail_id})


def reject(svc: Services, video_id: str, reason: str = "") -> None:
    rec = svc.db.require_video(video_id)
    if rec.status not in (VideoStatus.final_review, VideoStatus.script_review):
        raise ReviewError(f"reject из статуса {rec.status.value} невозможен")
    svc.db.update_video(video_id, status=VideoStatus.rejected, final_approved=False)
    svc.db.add_review_action(video_id, "final", "reject", {"reason": reason})
