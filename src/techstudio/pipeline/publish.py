"""Публикация на YouTube: длинное (главы в описании, SRT, теги, footer, миниатюра) + шортсы после него.
Идемпотентна: повторный вызов догружает только то, что не загружено."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime

from techstudio.assemble import chapters as chap
from techstudio.core import log
from techstudio.pipeline import orchestrator, scripts
from techstudio.publish import scheduler
from techstudio.publish.base import PublishError
from techstudio.schemas import FailureInfo, Publication, VideoAssembly, VideoMeta, VideoStatus
from techstudio.services import Services

_log = log.get("publish")


class PublishStateError(RuntimeError):
    pass


def long_description(meta: VideoMeta, asm: VideoAssembly, footer: str) -> str:
    parts = [meta.description.strip()]
    if asm.chapters_valid:
        parts.append(chap.to_text(asm.chapters, asm.duration).strip())
    if footer.strip():
        parts.append(footer.strip())
    return "\n\n".join(p for p in parts if p)


def short_texts(
    meta: VideoMeta, hook: str | None, long_url: str | None, footer: str
) -> tuple[str, str]:
    base = (hook or meta.title).strip().rstrip(".")
    title = (base[:88] + " #shorts") if "#shorts" not in base else base[:100]
    desc = [hook or meta.title]
    if long_url:
        desc.append(f"Полное видео: {long_url}")
    if footer.strip():
        desc.append(footer.strip())
    return title, "\n\n".join(desc)


def plan_publications(
    svc: Services, video_id: str, short_specs: list[dict], mine: dict, others: list, now: datetime
):
    """Слоты публикаций. Пока длинное не загружено — план целиком заново (на YouTube ничего нет);
    после — сохраняем время загруженных и будущих, просроченные шортсы перепланируем (publishAt в прошлом
    YouTube не примет)."""
    ch = svc.channel
    long_id = f"{video_id}:long"
    short_ids = [f"{video_id}:{s['id']}" for s in short_specs]
    earliest = now + scheduler.LEAD
    long_pub = mine.get(long_id)
    if long_pub is None or long_pub.remote_id is None:
        long_at, short_at = scheduler.plan(ch, others, now, len(short_specs))
        pubs = [
            (
                long_pub
                or Publication(
                    id=long_id,
                    video_id=video_id,
                    kind="long",
                    account_id=ch.account_id,
                    scheduled_at=long_at,
                )
            ).model_copy(update={"scheduled_at": long_at})
        ]
        for spec, pid, at in zip(short_specs, short_ids, short_at, strict=True):
            base = mine.get(pid) or Publication(
                id=pid,
                video_id=video_id,
                kind="short",
                short_id=spec["id"],
                account_id=ch.account_id,
                scheduled_at=at,
            )
            pubs.append(base.model_copy(update={"scheduled_at": at}))
        return pubs
    keep = {pid: p for pid, p in mine.items() if p.remote_id or p.scheduled_at >= earliest}
    need = [
        (spec, pid) for spec, pid in zip(short_specs, short_ids, strict=True) if pid not in keep
    ]
    fresh: list[datetime] = []
    if need:
        _, fresh = scheduler.plan(ch, others + list(keep.values()), now, len(need))
    it = iter(fresh)
    pubs = [long_pub]
    for spec, pid in zip(short_specs, short_ids, strict=True):
        if pid in keep:
            pubs.append(keep[pid])
        else:
            at = next(it)
            base = mine.get(pid) or Publication(
                id=pid,
                video_id=video_id,
                kind="short",
                short_id=spec["id"],
                account_id=ch.account_id,
                scheduled_at=at,
            )
            pubs.append(base.model_copy(update={"scheduled_at": at}))
    return pubs


def export_thumbnail(svc: Services, video_id: str, image, reason: str):
    out_dir = svc.storage.ensure_dir(f"exports/{video_id}")
    target = out_dir / "thumbnail.jpg"
    shutil.copyfile(image, target)
    (out_dir / "README.txt").write_text(
        f"Миниатюра не загрузилась через API: {reason}\nЗагрузи вручную в YouTube Studio: {target.name}\n",
        encoding="utf-8",
    )
    return target


def publish_video(svc: Services, video_id: str, now: datetime | None = None) -> list[Publication]:
    with orchestrator.video_lock(svc, video_id):  # двойной клик в боте не загрузит дважды
        return _publish_video(svc, video_id, now)


def _publish_video(svc: Services, video_id: str, now: datetime | None = None) -> list[Publication]:
    now = now or datetime.now(UTC)
    rec = svc.db.require_video(video_id)
    if rec.status not in (VideoStatus.final_review, VideoStatus.scheduled):
        raise PublishStateError(f"публикация из статуса {rec.status.value} невозможна")
    if not rec.final_approved:
        raise PublishStateError(
            "нет финального одобрения Босса (studio review VIDEO approve --thumb X)"
        )
    summary = orchestrator.final_summary(svc, video_id)
    if summary is None:
        raise PublishStateError("нет результата рендера")
    script = scripts.load_script(svc, video_id)
    ch = svc.channel
    asm = VideoAssembly.model_validate(summary["long"])
    meta = VideoMeta.model_validate(summary["meta"])
    short_specs = summary["shorts"]
    thumb = next(t for t in summary["thumbnails"] if t["id"] == rec.thumbnail_id)

    mine = {p.id: p for p in svc.db.list_publications(video_id)}
    others = [p for p in svc.db.list_publications() if p.video_id != video_id]
    pubs = plan_publications(svc, video_id, short_specs, mine, others, now)
    for p in pubs:
        svc.db.upsert_publication(p)

    publisher = svc.publisher
    try:
        long_pub = pubs[0]
        if long_pub.remote_id is None:
            remote = publisher.upload(
                svc.storage.path(asm.long_key),
                title=meta.title,
                description=long_description(meta, asm, ch.description_footer),
                tags=meta.tags,
                language=ch.language,
                publish_at=long_pub.scheduled_at,
            )
            long_pub = long_pub.model_copy(
                update={
                    "remote_id": remote,
                    "url": f"https://youtu.be/{remote}",
                    "status": "uploaded",
                }
            )
            svc.db.upsert_publication(long_pub)
            publisher.upload_captions(
                remote, svc.storage.path(asm.captions_key), ch.language, "Русский"
            )
            image = svc.storage.path(thumb["image_key"])
            try:
                publisher.set_thumbnail(remote, image)
            except PublishError as e:
                target = export_thumbnail(svc, video_id, image, str(e))
                long_pub = long_pub.model_copy(
                    update={
                        "notes": [*long_pub.notes, f"миниатюра вручную: {svc.storage.key(target)}"]
                    }
                )
                svc.db.upsert_publication(long_pub)
            pubs[0] = long_pub
        for i, (spec, p) in enumerate(zip(short_specs, pubs[1:], strict=True), 1):
            if p.remote_id is not None:
                continue
            scene_hook = next(
                (s.short_hook for s in script.scenes if s.id in spec["scene_ids"]), None
            )
            title, desc = short_texts(meta, scene_hook, pubs[0].url, ch.description_footer)
            remote = publisher.upload(
                svc.storage.path(spec["video_key"]),
                title=title,
                description=desc,
                tags=[*meta.tags, "shorts"],
                language=ch.language,
                publish_at=p.scheduled_at,
            )
            pubs[i] = p.model_copy(
                update={
                    "remote_id": remote,
                    "url": f"https://youtube.com/shorts/{remote}",
                    "status": "uploaded",
                }
            )
            svc.db.upsert_publication(pubs[i])
    except PublishError as e:
        svc.db.update_video(
            video_id,
            failure=FailureInfo(
                stage="publish", error_type=type(e).__name__, message=str(e), retryable=e.retryable
            ),
        )
        raise
    svc.db.update_video(video_id, status=VideoStatus.scheduled, failure=None)
    svc.db.add_review_action(
        video_id,
        "publish",
        "scheduled",
        {"long_at": pubs[0].scheduled_at.isoformat(), "shorts": len(pubs) - 1},
    )
    svc.storage.write_text(
        f"videos/{video_id}/publish.json",
        json.dumps([p.model_dump(mode="json") for p in pubs], ensure_ascii=False, indent=2),
    )
    _log.info(
        "publish.scheduled",
        video_id=video_id,
        long_at=pubs[0].scheduled_at.isoformat(),
        shorts=len(pubs) - 1,
    )
    return pubs


def mark_published(svc: Services, now: datetime | None = None) -> int:
    """Публикации с наступившим publishAt → published; видео — published, когда вышло длинное."""
    now = now or datetime.now(UTC)
    n = 0
    for p in svc.db.list_publications():
        if p.status == "uploaded" and p.scheduled_at <= now:
            svc.db.upsert_publication(p.model_copy(update={"status": "published"}))
            n += 1
            if p.kind == "long":
                rec = svc.db.get_video(p.video_id)
                if rec and rec.status == VideoStatus.scheduled:
                    svc.db.update_video(p.video_id, status=VideoStatus.published)
    return n
