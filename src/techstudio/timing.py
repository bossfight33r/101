"""Тайминг: оценка длительности по словам, длительность сцены, выравнивание слов, подгонка визуала."""

from __future__ import annotations

import re

WORD_RE = re.compile(r"\S+")


def count_words(text: str) -> int:
    return len(WORD_RE.findall(text or ""))


def estimate_speech(text: str, wpm: int) -> float:
    return count_words(text) * 60.0 / wpm


def scene_duration(
    narration_sec: float,
    *,
    min_sec: float,
    visual_min: float,
    pause_before: float,
    pause_after: float,
) -> float:
    """Длительность сцены = max(озвучка + паузы, минимум сцены, минимум визуала)."""
    return round(max(narration_sec + pause_before + pause_after, min_sec, visual_min), 3)


# ---------- выравнивание слов: тайминги ASR → исходный текст (для субтитров) ----------

_PUNCT = re.compile(r"[^\w]+", re.U)


def _norm(token: str) -> str:
    return _PUNCT.sub("", token.lower().replace("ё", "е"))


def align_words(original: str, asr_words: list, duration: float):
    """Исходные слова сценария получают тайминги из транскрипта TTS-аудио.
    Совпавшие (difflib) берут время ASR, несовпавшие (термины из словаря произношения и т.п.)
    распределяются между соседними якорями пропорционально длине."""
    from difflib import SequenceMatcher

    from techstudio.schemas import Word

    tokens = original.split()
    if not tokens:
        return []
    times: list[tuple[float, float] | None] = [None] * len(tokens)
    if asr_words:
        a = [_norm(t) for t in tokens]
        b = [_norm(w.text) for w in asr_words]
        for block in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
            for k in range(block.size):
                w = asr_words[block.b + k]
                times[block.a + k] = (w.start, w.end)
        span_start = asr_words[0].start
        span_end = asr_words[-1].end
    else:
        span_start, span_end = 0.0, duration
    i = 0
    while i < len(tokens):
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < len(tokens) and times[j] is None:
            j += 1
        left = times[i - 1][1] if i > 0 else span_start
        right = times[j][0] if j < len(tokens) else span_end
        if right <= left:
            right = left + 0.08 * (j - i)
        weights = [max(len(t), 1) for t in tokens[i:j]]
        total = sum(weights)
        cur = left
        for k, wgt in zip(range(i, j), weights, strict=True):
            step = (right - left) * wgt / total
            times[k] = (cur, cur + step)
            cur += step
        i = j
    return [
        Word(text=t, start=round(s, 3), end=round(e, 3))
        for t, (s, e) in zip(tokens, times, strict=True)
    ]


# ---------- подгонка визуала под длительность сцены ----------


def fit_args(visual_duration: float, target: float, eps: float = 0.04) -> list[str]:
    """Аргументы фильтра: короче — freeze последнего кадра (tpad), длиннее — обрезаем хвост."""
    if visual_duration < target - eps:
        pad = target - visual_duration
        return ["-vf", f"tpad=stop_mode=clone:stop_duration={pad:.3f}", "-t", f"{target:.3f}"]
    return ["-t", f"{target:.3f}"]


def fit_visual(src, out, target: float, encoder) -> float:
    from techstudio.core import ffmpeg, probe

    dur = probe.probe(src).duration
    ffmpeg.run(["-i", str(src), *fit_args(dur, target), *encoder.args(fps=30), "-an", str(out)])
    return probe.probe(out).duration
