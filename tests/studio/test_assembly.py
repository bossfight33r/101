import pytest

from techstudio.assemble import chapters as chap
from techstudio.assemble import longform
from techstudio.core import captions, ffmpeg, probe
from techstudio.core.encoder import X264_FAST
from techstudio.schemas import Chapter, Word
from techstudio.timing import align_words, fit_args, fit_visual, scene_duration

from .conftest import needs_ffmpeg


def _color(path, w, h, dur):
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            f"color=c=red:size={w}x{h}:rate=30:duration={dur}",
            *X264_FAST.args(),
            str(path),
        ]
    )
    return path


def test_scene_duration_never_cuts_voice():
    assert scene_duration(7.0, min_sec=3, visual_min=2, pause_before=0.3, pause_after=0.5) == 7.8
    assert scene_duration(2.0, min_sec=10, visual_min=2, pause_before=0.3, pause_after=0.5) == 10
    assert scene_duration(2.0, min_sec=0, visual_min=6, pause_before=0.3, pause_after=0.5) == 6


def test_fit_args_freeze_or_trim():
    assert "tpad=stop_mode=clone:stop_duration=3.000" in fit_args(2.0, 5.0)[1]
    assert fit_args(8.0, 5.0) == ["-t", "5.000"]


@needs_ffmpeg
def test_freeze_padding_extends_short_visual(tmp_path):
    src = _color(tmp_path / "v.mp4", 320, 180, 1.0)
    out = tmp_path / "fit.mp4"
    assert fit_visual(src, out, 3.0, X264_FAST) == pytest.approx(3.0, abs=0.1)
    out2 = tmp_path / "trim.mp4"
    assert fit_visual(
        _color(tmp_path / "long.mp4", 320, 180, 5.0), out2, 2.0, X264_FAST
    ) == pytest.approx(2.0, abs=0.1)


@needs_ffmpeg
def test_segment_freezes_visual_and_keeps_full_narration(tmp_path):
    visual = _color(tmp_path / "v.mp4", 1920, 1080, 1.0)
    voice = tmp_path / "n.wav"
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=300:duration=2.5",
            "-ar",
            "48000",
            "-ac",
            "1",
            str(voice),
        ]
    )
    seg = longform.build_segment(
        visual,
        voice,
        tmp_path / "s.mp4",
        duration=3.5,
        pause_before=0.3,
        encoder=X264_FAST,
        visual_duration=1.0,
    )
    info = probe.validate_video(
        seg, width=1920, height=1080, expected_duration=3.5, tolerance=0.1, need_audio=True
    )
    assert info.has_audio


def T(sid, ch, start, dur):
    return chap.TimedScene(sid, ch, start, dur)


def test_chapters_first_at_zero_and_min_three():
    scenes = [
        T("hook", None, 0, 6),
        T("a", "План", 6, 20),
        T("b", "Шаг 1", 26, 30),
        T("c", "Итоги", 56, 15),
    ]
    chs = chap.build_chapters(scenes)
    assert chs[0].start == 0 and chs[0].title == "План"  # хук < 10 с входит в первую главу
    ok, _ = chap.validate_chapters(chs, 71)
    assert ok and len(chs) == 3
    assert chap.to_text(chs, 71).splitlines()[0] == "00:00 План"


def test_chapters_long_intro_gets_own_chapter():
    scenes = [T("hook", None, 0, 12), T("a", "Шаг 1", 12, 20), T("b", "Шаг 2", 32, 20)]
    chs = chap.build_chapters(scenes)
    assert [c.title for c in chs] == ["Вступление", "Шаг 1", "Шаг 2"]


def test_chapters_short_ones_merged():
    scenes = [
        T("hook", None, 0, 5),
        T("a", "A", 5, 20),
        T("b", "B", 25, 4),
        T("c", "C", 29, 20),
        T("d", "D", 49, 20),
    ]
    chs = chap.build_chapters(scenes)
    ok, reason = chap.validate_chapters(chs, 69)
    assert ok, reason
    assert "B" not in [c.title for c in chs]


def test_chapters_validation_rules():
    assert not chap.validate_chapters(
        [Chapter(start=0, title="a"), Chapter(start=20, title="b")], 60
    )[0]
    assert not chap.validate_chapters(
        [Chapter(start=1, title="a"), Chapter(start=20, title="b"), Chapter(start=40, title="c")],
        60,
    )[0]
    assert not chap.validate_chapters(
        [Chapter(start=0, title="a"), Chapter(start=20, title="b"), Chapter(start=25, title="c")],
        60,
    )[0]
    assert chap.fmt_ts(3725) == "1:02:05" and chap.fmt_ts(65) == "01:05"


def test_align_words_maps_pronunciation_back():
    asr = [
        Word(text=t, start=i * 0.5, end=i * 0.5 + 0.4)
        for i, t in enumerate(["заходим", "по", "эс-эс-аш", "на", "роутер"])
    ]
    words = align_words("Заходим по SSH на роутер.", asr, 3.0)
    assert [w.text for w in words] == ["Заходим", "по", "SSH", "на", "роутер."]
    assert words[0].start == 0 and words[4].start == 2.0
    assert words[1].end <= words[2].start < words[3].start  # интерполяция между якорями


def test_align_words_without_asr_spreads_evenly():
    words = align_words("раз два три", [], 3.0)
    assert words[0].start == 0 and words[-1].end == pytest.approx(3.0)


def test_srt_and_ass():
    words = [
        Word(text=t, start=i * 0.4, end=i * 0.4 + 0.35)
        for i, t in enumerate("Смотрим порты. Ключ t это TCP, а u это UDP.".split())
    ]
    srt = captions.to_srt(words)
    assert srt.startswith("1\n00:00:00,000 --> ") and "Смотрим порты." in srt.split("\n\n")[0]
    ass = captions.to_ass(words, highlight="#22d3ee")
    assert "PlayResY: 1920" in ass and "\\c&H00EED322" in ass
    assert ass.count("Dialogue:") == len(words)
