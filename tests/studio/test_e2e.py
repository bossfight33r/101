"""E2E: тема → fake сценарий → approve → fake визуалы → fake голос → сборка → 16:9 с главами и SRT + шорт 9:16."""

import json

import pytest

from techstudio.core import probe
from techstudio.pipeline import orchestrator, scripts, stages
from techstudio.schemas import VideoStatus

from .conftest import needs_ffmpeg

pytestmark = [needs_ffmpeg, pytest.mark.slow]


def _replay_files(svc, script):
    for s in script.scenes:
        if s.type == "terminal" and s.mode == "replay":
            d = svc.storage.ensure_dir(s.replay_output_key)
            (d / "0.txt").write_text("HTTP/2 200\ncontent-type: text/html\n")


@pytest.fixture
def approved(svc, topic, small_channel):
    script, report = scripts.new_script(svc, topic.id)
    assert report.ok, [str(i) for i in report.issues]
    _replay_files(svc, script)
    scripts.approve(svc, script.video_id)
    return script


def test_e2e_long_and_shorts(svc, approved):
    vid = approved.video_id
    steps = []
    summary = orchestrator.render_video(svc, vid, progress=steps.append)
    assert [x.split()[0] for x in steps] == ["🎙", "🎞", "🧩", "📱", "🏷"]
    rec = svc.db.require_video(vid)
    assert rec.status == VideoStatus.final_review

    long_path = svc.storage.path(summary["long"]["long_key"])
    info = probe.validate_video(long_path, width=1920, height=1080, need_audio=True)
    assert info.fps == pytest.approx(30, abs=0.1)
    assert summary["long"]["chapters_valid"], summary["warnings"]

    chapters = (svc.video_dir(vid) / "chapters.txt").read_text().splitlines()
    assert chapters[0].startswith("00:00 ") and len(chapters) >= 3

    srt = (svc.video_dir(vid) / "captions.srt").read_text()
    assert "-->" in srt and "Набираем" in srt

    assert summary["shorts"], summary["warnings"]
    short = summary["shorts"][0]
    sinfo = probe.validate_video(
        svc.storage.path(short["video_key"]), width=1080, height=1920, need_audio=True
    )
    assert sinfo.duration <= 60
    assert (svc.storage.path(short["video_key"]).parent / "captions.ass").exists()

    assert len(summary["thumbnails"]) == 3
    assert all(svc.storage.path(t["image_key"]).exists() for t in summary["thumbnails"])
    assert svc.storage.path(summary["preview_key"]).exists()
    # флаги replay видны на финальном ревью
    assert any(f["mode"] == "replay" for f in summary["flags"])

    # раскладка из ТЗ
    sdir = svc.video_dir(vid) / "scenes" / "cmd1"
    for name in (
        "narration.wav",
        "words.json",
        "visual_16x9.mp4",
        "visual_9x16.mp4",
        "manifest.json",
    ):
        assert (sdir / name).exists(), name
    assert (svc.video_dir(vid) / "meta.json").exists()

    # повтор без изменений — всё из кеша
    again = orchestrator.render_video(svc, vid)
    assert again["ran"] == []


def test_resume_after_assembly_failure_keeps_voice_and_visuals(svc, approved, monkeypatch):
    vid = approved.video_id
    calls = {"n": 0}
    real = stages.run_long

    def broken(ctx):
        calls["n"] += 1
        raise RuntimeError("диск кончился")

    monkeypatch.setattr(stages, "run_long", broken)
    with pytest.raises(RuntimeError):
        orchestrator.render_video(svc, vid)
    rec = svc.db.require_video(vid)
    assert rec.status == VideoStatus.failed
    assert (
        rec.failure.stage == "assembling"
        and rec.failure.error_type == "RuntimeError"
        and rec.failure.retryable
    )

    tts_calls = len(svc.tts.calls)
    asr_calls = svc.transcriber.calls
    visual = svc.video_dir(vid) / "scenes" / "cmd1" / "visual_16x9.mp4"
    mtime = visual.stat().st_mtime_ns

    monkeypatch.setattr(stages, "run_long", real)
    summary = orchestrator.retry(svc, vid)
    assert len(svc.tts.calls) == tts_calls  # озвучка не переделывалась
    assert svc.transcriber.calls == asr_calls
    assert visual.stat().st_mtime_ns == mtime  # визуалы не перерендерились
    assert not any(r.startswith(("cmd1/voice", "cmd1/visual")) for r in summary["ran"])
    assert "long" in summary["ran"]
    assert svc.db.require_video(vid).status == VideoStatus.final_review


def test_rerender_scene_only_touches_that_scene(svc, approved):
    vid = approved.video_id
    orchestrator.render_video(svc, vid)
    summary = orchestrator.rerender_scene(svc, vid, "code")
    ran_visuals = {r.split("/")[0] for r in summary["ran"] if "/visual:" in r}
    assert ran_visuals == {"code"}
    assert not any(r.startswith("cmd1/") for r in summary["ran"])


def test_render_requires_approve(svc, topic, small_channel):
    script, _ = scripts.new_script(svc, topic.id)
    with pytest.raises(orchestrator.NotApprovedError):
        orchestrator.render_video(svc, script.video_id)
    assert not (svc.video_dir(script.video_id) / "scenes").exists()


def test_pronunciation_not_in_subtitles(svc, topic, small_channel):
    script, _ = scripts.new_script(svc, topic.id)
    _replay_files(svc, script)
    scripts.approve(svc, script.video_id)
    ctx = stages.make_ctx(svc, scripts.load_script(svc, script.video_id))
    na = stages._voice_one(ctx, "x", "Заходим по SSH на OpenWrt.", "narration")
    assert any("эс-эс-аш" in t for t in svc.tts.calls)  # TTS получил произношение
    assert [w.text for w in na.words] == [
        "Заходим",
        "по",
        "SSH",
        "на",
        "OpenWrt.",
    ]  # субтитры — исходник
    data = json.loads((ctx.scene_dir("x") / "words.json").read_text())
    assert data[2]["text"] == "SSH"


def test_selftest_reports_fake_terminal_and_fallback(settings, tmp_path):
    """selftest с fake-рендерами: конвейер проходит, но честно помечает, что Docker/mermaid не проверены."""
    from techstudio import selftest

    settings.__dict__["channel"] = settings.channel
    res = selftest.run(settings, tmp_path / "st", real=False, keep=False)
    checks = {name: ok for name, ok, _ in res.checks}
    assert checks["сценарий (fake LLM) + валидация"] and checks["длинное видео 1920x1080"]
    assert (
        checks["терминал: Docker + VHS (live, files, replay)"] is False
    )  # fake-визуал не выдаётся за реальный
    assert res.long_path.exists() and not res.ok
