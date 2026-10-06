"""Субтитры: SRT для длинного видео (не вшиваем) и ASS с подсветкой слова для шортсов."""

from __future__ import annotations

from dataclasses import dataclass

from techstudio.schemas import Word

SENTENCE_END = (".", "!", "?", "…", ":")


@dataclass
class Cue:
    start: float
    end: float
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def group_words(
    words: list[Word], *, max_chars: int = 42, max_sec: float = 3.5, max_words: int = 12
) -> list[Cue]:
    cues: list[Cue] = []
    cur: list[Word] = []
    for w in words:
        if cur:
            text_len = len(" ".join(x.text for x in cur)) + 1 + len(w.text)
            too_long = (
                text_len > max_chars or (w.end - cur[0].start) > max_sec or len(cur) >= max_words
            )
            if too_long:
                cues.append(Cue(cur[0].start, cur[-1].end, cur))
                cur = []
        cur.append(w)
        if w.text.endswith(SENTENCE_END):
            cues.append(Cue(cur[0].start, cur[-1].end, cur))
            cur = []
    if cur:
        cues.append(Cue(cur[0].start, cur[-1].end, cur))
    # без пересечений и с минимальной длительностью
    for i, c in enumerate(cues):
        nxt = cues[i + 1].start if i + 1 < len(cues) else None
        c.end = max(c.end, c.start + 0.5)
        if nxt is not None:
            c.end = min(c.end, nxt)
    return cues


def _ts_srt(t: float) -> str:
    ms = int(round(max(t, 0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(words: list[Word]) -> str:
    out = []
    for i, cue in enumerate(group_words(words), 1):
        out.append(f"{i}\n{_ts_srt(cue.start)} --> {_ts_srt(cue.end)}\n{cue.text}\n")
    return "\n".join(out)


def _ts_ass(t: float) -> str:
    cs = int(round(max(t, 0) * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def _ass_color(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def to_ass(
    words: list[Word],
    *,
    width: int = 1080,
    height: int = 1920,
    font: str = "DejaVu Sans",
    size: int = 84,
    color: str = "#FFFFFF",
    highlight: str = "#22D3EE",
    margin_v: int = 560,
) -> str:
    """Пословная подсветка: на каждое слово группы — событие, где текущее слово окрашено.
    margin_v держит текст выше нижней UI-зоны Shorts (safe zone)."""
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},{_ass_color(color)},{_ass_color(color)},&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,5,2,2,80,80,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    hl = _ass_color(highlight)
    lines = []
    for cue in group_words(words, max_chars=22, max_sec=2.5, max_words=4):
        for i, w in enumerate(cue.words):
            start = w.start if i else cue.start
            end = cue.words[i + 1].start if i + 1 < len(cue.words) else cue.end
            if end <= start:
                continue
            parts = []
            for j, x in enumerate(cue.words):
                t = _ass_escape(x.text)
                parts.append(f"{{\\c{hl}}}{t}{{\\c{_ass_color(color)}}}" if j == i else t)
            lines.append(
                f"Dialogue: 0,{_ts_ass(start)},{_ts_ass(end)},Default,,0,0,0,,{' '.join(parts)}"
            )
    return header + "\n".join(lines) + "\n"


def shift(words: list[Word], offset: float) -> list[Word]:
    return [
        w.model_copy(update={"start": round(w.start + offset, 3), "end": round(w.end + offset, 3)})
        for w in words
    ]
