import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from techstudio.pipeline import publish, review, scripts
from techstudio.publish import scheduler
from techstudio.publish.fake import FakePublisher
from techstudio.schemas import Chapter, DailyLimits, Publication, ScheduleConfig, VideoStatus

MSK = ZoneInfo("Europe/Moscow")


def _ch(svc, **kw):
    return svc.channel.model_copy(update=kw)


def test_plan_long_then_shorts_with_interval(svc):
    now = datetime(2026, 10, 6, 9, 0, tzinfo=MSK)
    long_at, shorts = scheduler.plan(svc.channel, [], now, 3)
    assert long_at.astimezone(MSK) == datetime(2026, 10, 6, 18, 0, tzinfo=MSK)
    # 3 шортса/день: 22:00 сегодня, затем перенос на завтра (02:00 07.10 — уже другой день)
    loc = [t.astimezone(MSK) for t in shorts]
    assert loc[0] == datetime(2026, 10, 6, 22, 0, tzinfo=MSK)
    assert all(
        b - a >= timedelta(hours=4) for a, b in zip([long_at, *shorts], shorts, strict=False)
    )
    assert all(t > long_at for t in shorts)


def test_plan_after_long_time_moves_to_tomorrow(svc):
    now = datetime(2026, 10, 6, 17, 50, tzinfo=MSK)  # меньше 30 мин до слота
    long_at, _ = scheduler.plan(svc.channel, [], now, 0)
    assert long_at.astimezone(MSK).date().day == 7


def test_daily_limits_respected(svc):
    ch = _ch(
        svc,
        daily_limits=DailyLimits(long=1, shorts=2),
        schedule=ScheduleConfig(
            timezone="Europe/Moscow", long_time="10:00", shorts_interval_hours=1
        ),
    )
    now = datetime(2026, 10, 6, 6, 0, tzinfo=MSK)
    existing = [
        Publication(
            id="x:long",
            video_id="x",
            kind="long",
            account_id="a",
            scheduled_at=datetime(2026, 10, 6, 10, 0, tzinfo=MSK),
        ),
        Publication(
            id="x:s1",
            video_id="x",
            kind="short",
            account_id="a",
            scheduled_at=datetime(2026, 10, 6, 11, 0, tzinfo=MSK),
        ),
    ]
    long_at, shorts = scheduler.plan(ch, existing, now, 4)
    assert long_at.astimezone(MSK).date().day == 7  # 6-е занято
    days = [t.astimezone(MSK).date() for t in shorts]
    counts = {d: days.count(d) for d in set(days)}
    assert all(c <= 2 for c in counts.values())
    # failed не занимает лимит
    existing[0] = existing[0].model_copy(update={"status": "failed"})
    long_at2, _ = scheduler.plan(ch, existing, now, 0)
    assert long_at2.astimezone(MSK).date().day == 6


def test_zero_limit_raises(svc):
    with pytest.raises(scheduler.ScheduleError):
        scheduler.plan(_ch(svc, daily_limits=DailyLimits(long=0)), [], datetime.now(UTC), 0)


def test_dst_local_time_kept(svc):
    ch = _ch(
        svc,
        schedule=ScheduleConfig(
            timezone="Europe/Berlin", long_time="18:00", shorts_interval_hours=4
        ),
    )
    berlin = ZoneInfo("Europe/Berlin")
    long_at, _ = scheduler.plan(
        ch, [], datetime(2026, 10, 25, 8, 0, tzinfo=berlin), 0
    )  # день перехода на зимнее
    assert long_at.astimezone(berlin).hour == 18 and long_at.utcoffset() == timedelta(0)
    assert long_at.astimezone(UTC).hour == 17


# ---------------- публикация ----------------


@pytest.fixture
def ready(svc, topic):
    """Видео в final_review с файлами-заглушками (публикация файлы не перекодирует)."""
    script, _ = scripts.new_script(svc, topic.id)
    vid = script.video_id
    vdir = svc.video_dir(vid)
    for rel in (
        "long.mp4",
        "captions.srt",
        "shorts/short-cmd1/final.mp4",
        "shorts/short-code/final.mp4",
        "thumbs/A.jpg",
        "thumbs/B.jpg",
        "thumbs/C.jpg",
        "preview.mp4",
    ):
        (vdir / rel).parent.mkdir(parents=True, exist_ok=True)
        (vdir / rel).write_bytes(b"x")
    summary = {
        "video_id": vid,
        "long": {
            "video_id": vid,
            "long_key": f"videos/{vid}/long.mp4",
            "captions_key": f"videos/{vid}/captions.srt",
            "chapters": [
                Chapter(start=0, title="План").model_dump(),
                Chapter(start=20, title="Шаг 1").model_dump(),
                Chapter(start=60, title="Итоги").model_dump(),
            ],
            "duration": 400.0,
            "chapters_valid": True,
        },
        "preview_key": f"videos/{vid}/preview.mp4",
        "shorts": [
            {
                "id": "short-cmd1",
                "scene_ids": ["cmd1"],
                "hook": "h",
                "duration": 20,
                "video_key": f"videos/{vid}/shorts/short-cmd1/final.mp4",
            },
            {
                "id": "short-code",
                "scene_ids": ["code"],
                "hook": "h",
                "duration": 20,
                "video_key": f"videos/{vid}/shorts/short-code/final.mp4",
            },
        ],
        "thumbnails": [
            {"id": x, "image_key": f"videos/{vid}/thumbs/{x}.jpg", "text": x} for x in "ABC"
        ],
        "meta": {
            "title": "ss: кто слушает порты",
            "description": "Пошагово.",
            "tags": ["linux"],
            "thumbnail_texts": [],
        },
        "warnings": [],
        "flags": [{"scene_id": "cmd2", "mode": "replay", "network": False}],
        "ran": [],
        "cache_hits": [],
    }
    svc.storage.write_text(
        f"videos/{vid}/final_review.json", json.dumps(summary, ensure_ascii=False)
    )
    svc.db.update_video(vid, status=VideoStatus.final_review)
    return vid


NOW = datetime(2026, 10, 6, 9, 0, tzinfo=MSK)


def test_no_publish_without_final_approve(svc, ready):
    with pytest.raises(publish.PublishStateError, match="одобрения"):
        publish.publish_video(svc, ready, NOW)
    with pytest.raises(review.ReviewError, match="миниатюру"):
        review.approve(svc, ready)
    assert svc.publisher.uploads == []


def test_publish_long_and_shorts(svc, ready):
    review.approve(svc, ready, "B")
    pubs = publish.publish_video(svc, ready, NOW)
    yt: FakePublisher = svc.publisher
    long_up, *short_ups = yt.uploads
    assert (
        "00:00 План" in long_up["description"] and "Telegram" in long_up["description"]
    )  # главы + footer
    assert long_up["tags"] == ["linux"] and long_up["publish_at"] == pubs[0].scheduled_at
    assert yt.captions[0][0] == long_up["id"] and yt.captions[0][1].name == "captions.srt"
    assert yt.thumbnails[0][1].name == "B.jpg"
    assert len(short_ups) == 2 and all("#shorts" in s["title"] for s in short_ups)
    assert all(f"https://youtu.be/{long_up['id']}" in s["description"] for s in short_ups)
    assert all(s["publish_at"] > long_up["publish_at"] for s in short_ups)
    assert svc.db.require_video(ready).status == VideoStatus.scheduled
    # повтор идемпотентен
    publish.publish_video(svc, ready, NOW)
    assert len(yt.uploads) == 3


def test_thumbnail_failure_exports_for_manual_upload(svc, ready):
    svc.overrides["publisher"] = FakePublisher(fail_thumbnail=True)
    review.approve(svc, ready, "A")
    pubs = publish.publish_video(svc, ready, NOW)
    assert svc.storage.exists(f"exports/{ready}/thumbnail.jpg")
    assert any("вручную" in n for n in pubs[0].notes)


def test_invalid_chapters_not_in_description(svc, ready):
    data = json.loads(svc.storage.read_text(f"videos/{ready}/final_review.json"))
    data["long"]["chapters_valid"] = False
    svc.storage.write_text(f"videos/{ready}/final_review.json", json.dumps(data))
    review.approve(svc, ready, "A")
    publish.publish_video(svc, ready, NOW)
    assert "00:00" not in svc.publisher.uploads[0]["description"]


def test_second_video_respects_daily_limit(svc, ready, topic):
    review.approve(svc, ready, "A")
    first = publish.publish_video(svc, ready, NOW)
    script, _ = scripts.new_script(svc, topic.id)
    vid2 = script.video_id
    import shutil

    shutil.copytree(
        svc.video_dir(ready) / "thumbs", svc.video_dir(vid2) / "thumbs", dirs_exist_ok=True
    )
    data = json.loads(svc.storage.read_text(f"videos/{ready}/final_review.json"))
    svc.storage.write_text(f"videos/{vid2}/final_review.json", json.dumps(data))
    svc.db.update_video(vid2, status=VideoStatus.final_review)
    review.approve(svc, vid2, "A")
    second = publish.publish_video(svc, vid2, NOW)
    assert (
        second[0].scheduled_at.astimezone(MSK).date() > first[0].scheduled_at.astimezone(MSK).date()
    )
    days = [
        p.scheduled_at.astimezone(MSK).date()
        for p in svc.db.list_publications()
        if p.kind == "short"
    ]
    assert max(days.count(d) for d in days) <= svc.channel.daily_limits.shorts


def test_rejected_video_never_published(svc, ready):
    review.reject(svc, ready, "скучно")
    with pytest.raises(publish.PublishStateError):
        publish.publish_video(svc, ready, NOW)


def test_mark_published(svc, ready):
    review.approve(svc, ready, "A")
    pubs = publish.publish_video(svc, ready, NOW)
    assert publish.mark_published(svc, pubs[0].scheduled_at + timedelta(minutes=1)) == 1
    assert svc.db.require_video(ready).status == VideoStatus.published
    from techstudio.schemas import TopicStatus

    assert svc.db.get_topic(svc.db.require_video(ready).topic_id).status == TopicStatus.done


def test_concurrent_publish_blocked(svc, ready):
    from techstudio.pipeline import orchestrator

    review.approve(svc, ready, "A")
    with orchestrator.video_lock(svc, ready):
        with pytest.raises(orchestrator.BusyError):
            publish.publish_video(svc, ready, NOW)
    assert svc.publisher.uploads == []


def test_retry_after_failed_upload_replans_past_slots(svc, ready):
    """Загрузка упала, повтор через 3 дня: publishAt в прошлом YouTube не примет — план заново."""
    from techstudio.publish.base import PublishError

    class Flaky(FakePublisher):
        def __init__(self):
            super().__init__()
            self.fail = True

        def upload(self, file, **kw):
            if self.fail:
                raise PublishError("503", retryable=True)
            return super().upload(file, **kw)

    flaky = Flaky()
    svc.overrides["publisher"] = flaky
    review.approve(svc, ready, "A")
    with pytest.raises(PublishError):
        publish.publish_video(svc, ready, NOW)
    first_plan = {p.id: p.scheduled_at for p in svc.db.list_publications(ready)}
    assert svc.db.require_video(ready).failure.stage == "publish"

    later = NOW + timedelta(days=3)
    flaky.fail = False
    pubs = publish.publish_video(svc, ready, later)
    assert all(p.scheduled_at > later for p in pubs)
    assert pubs[0].scheduled_at != first_plan[f"{ready}:long"]
    assert all(s.scheduled_at > pubs[0].scheduled_at for s in pubs[1:])
    assert svc.db.require_video(ready).failure is None


def test_retry_after_long_uploaded_replans_only_stale_shorts(svc, ready):
    from techstudio.publish.base import PublishError

    class FailShorts(FakePublisher):
        def __init__(self):
            super().__init__()
            self.fail_shorts = True

        def upload(self, file, **kw):
            if self.fail_shorts and "#shorts" in kw["title"]:
                raise PublishError("quota", retryable=True)
            return super().upload(file, **kw)

    pub = FailShorts()
    svc.overrides["publisher"] = pub
    review.approve(svc, ready, "A")
    with pytest.raises(PublishError):
        publish.publish_video(svc, ready, NOW)
    long_before = next(p for p in svc.db.list_publications(ready) if p.kind == "long")
    assert long_before.remote_id
    pub.fail_shorts = False
    later = NOW + timedelta(days=2)
    pubs = publish.publish_video(svc, ready, later)
    assert (
        pubs[0].scheduled_at == long_before.scheduled_at
    )  # длинное уже на YouTube — время не трогаем
    assert all(p.scheduled_at > later for p in pubs[1:])
    assert (
        len([u for u in pub.uploads if "#shorts" not in u["title"]]) == 1
    )  # длинное не перезалито


def test_fake_visuals_block_final_approve(svc, ready):
    data = json.loads(svc.storage.read_text(f"videos/{ready}/final_review.json"))
    data["warnings"] = ["cmd1 16x9: fake-визуал"]
    svc.storage.write_text(f"videos/{ready}/final_review.json", json.dumps(data))
    with pytest.raises(review.ReviewError, match="фейковые"):
        review.approve(svc, ready, "A")
    from techstudio.bot import logic

    gate = logic.final_gate(svc, ready)[-1]
    assert "публикация недоступна" in gate.text
    assert not any("публикация" in b[0] for row in gate.buttons for b in row)
    svc.settings.allow_fake_publish = True  # явный отладочный флаг
    review.approve(svc, ready, "A")
    assert svc.db.require_video(ready).final_approved


def test_hashtags_in_long_description(svc, ready):
    svc.settings.__dict__["channel"] = svc.channel.model_copy(
        update={"hashtags": ["linux", "#OpenWrt", "сети", "linux", "a b"]}
    )
    review.approve(svc, ready, "A")
    publish.publish_video(svc, ready, NOW)
    desc = svc.publisher.uploads[0]["description"]
    assert desc.rstrip().endswith("#linux #OpenWrt #сети #ab")


def test_outro_has_end_screen_room(svc, topic):
    from techstudio.pipeline import stages

    script, _ = scripts.new_script(svc, topic.id)
    scenes = stages.service_scenes(script, "x", 10.0)
    assert scenes[-1].id == "outro" and scenes[-1].min_sec == 10.0
    assert scenes[0].id == "hook"


def test_shorts_not_at_night(svc):
    now = datetime(2026, 10, 6, 9, 0, tzinfo=MSK)
    long_at, shorts = scheduler.plan(svc.channel, [], now, 3)
    loc = [t.astimezone(MSK) for t in shorts]
    assert loc[0] == datetime(2026, 10, 6, 22, 0, tzinfo=MSK)
    assert loc[1] == datetime(2026, 10, 7, 8, 0, tzinfo=MSK)  # 02:00 → начало окна
    assert loc[2] == datetime(2026, 10, 7, 12, 0, tzinfo=MSK)
    assert all(8 <= t.hour <= 23 for t in loc)
