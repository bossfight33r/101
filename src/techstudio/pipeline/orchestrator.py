"""Оркестратор видео. Рендер возможен только для одобренной версии сценария — проверка здесь."""

from __future__ import annotations

import fcntl
import json
from collections.abc import Callable
from contextlib import contextmanager

from techstudio.core import log
from techstudio.pipeline import scripts, stages
from techstudio.schemas import FailureInfo, Script, VideoStatus
from techstudio.services import Services

_log = log.get("orchestrator")

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


# ---------------- полный прогон ----------------


def _fail(svc: Services, video_id: str, stage: str, e: Exception) -> None:
    retryable = getattr(e, "retryable", True)
    info = FailureInfo(
        stage=stage, error_type=type(e).__name__, message=str(e)[:800], retryable=bool(retryable)
    )
    svc.db.update_video(video_id, status=VideoStatus.failed, failure=info)
    _log.error("render.failed", video_id=video_id, stage=stage, error=info.error_type)


class BusyError(RuntimeError):
    retryable = True


@contextmanager
def video_lock(svc: Services, video_id: str):
    """Один рендер на видео (двойной клик в боте, CLI параллельно с ботом)."""
    path = svc.video_dir(video_id) / ".render.lock"
    with path.open("w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise BusyError(f"{video_id} уже рендерится") from e
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


Progress = Callable[[str], None]


def render_video(svc: Services, video_id: str, progress: Progress | None = None) -> dict:
    """approved → voicing → rendering → assembling → final_review. Повтор = resume по манифестам.
    progress — колбэк для человека (бот обновляет одно сообщение)."""
    with video_lock(svc, video_id):
        return _render_video(svc, video_id, progress or (lambda _msg: None))


def _render_video(svc: Services, video_id: str, progress: Progress) -> dict:
    script = ensure_renderable(svc, video_id)
    ctx = stages.make_ctx(svc, script)
    stage = "voicing"
    try:
        svc.db.update_video(video_id, status=VideoStatus.voicing, failure=None)
        progress("🎙 Озвучка и тайминги…")
        stages.run_voice(ctx)
        stage = "rendering"
        svc.db.update_video(video_id, status=VideoStatus.rendering)
        progress("🎞 Визуалы сцен…")
        stages.run_visuals(ctx)
        stage = "assembling"
        svc.db.update_video(video_id, status=VideoStatus.assembling)
        progress("🧩 Сборка длинного видео…")
        asm = stages.run_long(ctx)
        progress("📱 Шортсы…")
        short_specs = stages.run_shorts(ctx)
        progress("🏷 Метаданные, миниатюры, превью…")
        meta = stages.run_metadata(ctx)
        variants = stages.run_thumbnails(ctx, meta)
        preview = stages.run_preview(ctx, asm)
    except Exception as e:
        _fail(svc, video_id, stage, e)
        raise
    summary = {
        "video_id": video_id,
        "script_version": script.version,
        "long": asm.model_dump(),
        "preview_key": svc.storage.key(preview),
        "shorts": [s.model_dump() for s in short_specs],
        "thumbnails": [v.model_dump() for v in variants],
        "meta": meta.model_dump(),
        "warnings": ctx.warnings,
        "flags": [
            {"scene_id": s.id, "mode": s.mode, "network": s.network}
            for s in script.scenes
            if s.type == "terminal" and (s.network or s.mode == "replay")
        ],
        "ran": ctx.ran,
        "cache_hits": ctx.cache_hits,
    }
    svc.storage.write_text(
        f"videos/{video_id}/final_review.json", json.dumps(summary, ensure_ascii=False, indent=2)
    )
    svc.db.update_video(video_id, status=VideoStatus.final_review, final_approved=False)
    _log.info("render.done", video_id=video_id, ran=len(ctx.ran), cached=len(ctx.cache_hits))
    return summary


def retry(svc: Services, video_id: str, progress: Progress | None = None) -> dict:
    rec = svc.db.require_video(video_id)
    if rec.status != VideoStatus.failed:
        raise RuntimeError(f"retry только для failed (сейчас {rec.status.value})")
    if rec.failure and not rec.failure.retryable:
        _log.warning("retry.non_retryable", video_id=video_id, stage=rec.failure.stage)
    return render_video(svc, video_id, progress)


def rerender_scene(
    svc: Services, video_id: str, scene_id: str, progress: Progress | None = None
) -> dict:
    """Перерендер визуала одной сцены (гейт 2): сбрасываем её визуальные этапы и сегменты."""
    script = ensure_renderable(svc, video_id)
    ids = [s.id for s in stages.service_scenes(script, svc.channel.name)]
    if scene_id not in ids:
        raise KeyError(f"нет сцены {scene_id}")
    from techstudio.core.manifest import Manifest

    path = svc.video_dir(video_id) / "scenes" / scene_id / "manifest.json"
    m = Manifest.load(path)
    for name in list(m.stages):
        if name.startswith(("visual:", "segment:", "card:")):
            m.invalidate(name)
    m.save(path)
    svc.db.add_review_action(video_id, "final", "rerender_scene", {"scene_id": scene_id})
    return render_video(svc, video_id, progress)


def final_summary(svc: Services, video_id: str) -> dict | None:
    key = f"videos/{video_id}/final_review.json"
    return json.loads(svc.storage.read_text(key)) if svc.storage.exists(key) else None
