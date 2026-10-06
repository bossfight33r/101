"""Главы YouTube из сцен: первая 00:00, минимум 3, каждая от 10 секунд."""

from __future__ import annotations

from dataclasses import dataclass

from techstudio.schemas import Chapter

MIN_CHAPTER_SEC = 10.0
MIN_CHAPTERS = 3


@dataclass
class TimedScene:
    scene_id: str
    chapter: str | None
    start: float
    duration: float


def build_chapters(scenes: list[TimedScene], intro_title: str = "Вступление") -> list[Chapter]:
    if not scenes:
        return []
    total = scenes[-1].start + scenes[-1].duration
    chapters: list[Chapter] = []
    for s in scenes:
        if s.chapter:
            chapters.append(Chapter(start=round(s.start, 3), title=s.chapter.strip()))
    if not chapters:
        return [Chapter(start=0.0, title=intro_title)]
    # первая глава всегда 00:00: хук (и всё до первой главы) входит в первую главу,
    # если до неё меньше 10 с, иначе — отдельное «Вступление»
    if chapters[0].start > 0:
        if chapters[0].start < MIN_CHAPTER_SEC:
            chapters[0] = Chapter(start=0.0, title=chapters[0].title)
        else:
            chapters.insert(0, Chapter(start=0.0, title=intro_title))
    # склеиваем главы короче 10 с: короткая глава сливается с предыдущей (первая — со следующей)
    changed = True
    while changed and len(chapters) > 1:
        changed = False
        for i, ch in enumerate(chapters):
            end = chapters[i + 1].start if i + 1 < len(chapters) else total
            if end - ch.start < MIN_CHAPTER_SEC:
                if i == 0:
                    chapters.pop(1)
                else:
                    chapters.pop(i)
                changed = True
                break
    return chapters


def validate_chapters(chapters: list[Chapter], total: float) -> tuple[bool, str]:
    if len(chapters) < MIN_CHAPTERS:
        return False, f"глав {len(chapters)} < {MIN_CHAPTERS}: YouTube их не покажет"
    if chapters[0].start != 0:
        return False, "первая глава должна начинаться с 00:00"
    for i, ch in enumerate(chapters):
        end = chapters[i + 1].start if i + 1 < len(chapters) else total
        if end <= ch.start:
            return False, "главы не по возрастанию"
        if end - ch.start < MIN_CHAPTER_SEC:
            return False, f"глава «{ch.title}» короче {MIN_CHAPTER_SEC:.0f} с"
    return True, ""


def fmt_ts(sec: float, long_format: bool = False) -> str:
    s = int(sec)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if long_format or h else f"{m:02d}:{s:02d}"


def to_text(chapters: list[Chapter], total: float) -> str:
    long_format = total >= 3600
    return "\n".join(f"{fmt_ts(c.start, long_format)} {c.title}" for c in chapters) + "\n"
