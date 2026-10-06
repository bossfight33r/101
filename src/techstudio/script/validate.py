"""Валидация сценария сверх Pydantic: длительность, хук, шортсы, policy, mermaid, ассеты."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from techstudio.sandbox import policy
from techstudio.schemas import Channel, Script
from techstudio.timing import count_words, estimate_speech

HOOK_MAX_SEC = 10.0
SHORT_MAX_SEC = 58.0
BANNED_PHRASES = (
    "в этом видео мы рассмотрим",
    "в этом видео мы поговорим",
    "в этом ролике мы рассмотрим",
    "давайте разберёмся",
    "давайте разберемся",
    "всем привет, с вами",
)
MERMAID_HEADERS = {
    "graph",
    "flowchart",
    "sequenceDiagram",
    "classDiagram",
    "stateDiagram",
    "stateDiagram-v2",
    "erDiagram",
    "gantt",
    "pie",
    "journey",
    "mindmap",
    "timeline",
    "gitGraph",
    "quadrantChart",
    "requirementDiagram",
    "block-beta",
    "sankey-beta",
    "xychart-beta",
    "packet-beta",
    "architecture-beta",
}

MermaidChecker = Callable[[str], str | None]  # None = ок, иначе текст ошибки


@dataclass
class Issue:
    level: Literal["error", "warning"]
    scene_id: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.scene_id}: {self.message}"


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)
    estimated_sec: float = 0.0
    violations: list[policy.Violation] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, level, scene_id, message) -> None:
        self.issues.append(Issue(level, scene_id, message))

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "estimated_sec": round(self.estimated_sec, 1),
            "issues": [i.__dict__ for i in self.issues],
        }


def mermaid_basic_check(src: str) -> str | None:
    lines = [
        ln.strip() for ln in src.splitlines() if ln.strip() and not ln.strip().startswith("%%")
    ]
    if not lines:
        return "пустая диаграмма"
    head = re.split(r"[\s;]", lines[0], maxsplit=1)[0]
    if head not in MERMAID_HEADERS:
        return f"неизвестный тип диаграммы {head!r}"
    for o, c in ("[]", "()", "{}"):
        if src.count(o) != src.count(c):
            return f"несбалансированные скобки {o}{c}"
    return None


def estimate_scene_sec(scene, channel: Channel, pause: float = 0.8) -> float:
    return max(estimate_speech(scene.narration, channel.words_per_minute) + pause, scene.min_sec)


def estimate_total_sec(script: Script, channel: Channel) -> float:
    wpm = channel.words_per_minute
    total = estimate_speech(script.hook, wpm) + 0.8
    if script.outro:
        total += max(estimate_speech(script.outro, wpm) + 0.8, channel.outro_min_sec)
    return total + sum(estimate_scene_sec(s, channel) for s in script.scenes)


def validate_script(
    script: Script,
    channel: Channel,
    *,
    mermaid_checker: MermaidChecker | None = None,
    asset_exists: Callable[[str], bool] | None = None,
) -> ValidationReport:
    rep = ValidationReport()
    wpm = channel.words_per_minute

    # хук
    hook_sec = estimate_speech(script.hook, wpm)
    if hook_sec > HOOK_MAX_SEC:
        rep.add("error", "hook", f"хук ~{hook_sec:.0f} с, нужно ≤ {HOOK_MAX_SEC:.0f} с — сократи")

    # стиль
    texts = [("hook", script.hook), ("outro", script.outro)] + [
        (s.id, s.narration) for s in script.scenes
    ]
    for sid, text in texts:
        low = (text or "").lower()
        for phrase in BANNED_PHRASES:
            if phrase in low:
                rep.add("error", sid, f"запрещённая фраза «{phrase}»")

    # объём против целевой длительности
    rep.estimated_sec = estimate_total_sec(script, channel)
    lo, hi = channel.longform.min_sec, channel.longform.max_sec
    if rep.estimated_sec < lo:
        rep.add(
            "error", "-", f"оценка длительности {rep.estimated_sec:.0f} с < {lo} с: мало текста"
        )
    elif rep.estimated_sec > hi:
        rep.add(
            "error", "-", f"оценка длительности {rep.estimated_sec:.0f} с > {hi} с: много текста"
        )

    if not script.outro.strip():
        rep.add("warning", "outro", "нет аутро — некуда поставить конечную заставку YouTube")

    # шортсы
    shorts = [s for s in script.scenes if s.short_candidate]
    if not channel.short_candidates_min <= len(shorts) <= channel.short_candidates_max:
        rep.add(
            "warning",
            "-",
            f"сцен-кандидатов в шортсы {len(shorts)}, нужно {channel.short_candidates_min}–{channel.short_candidates_max}",
        )
    for s in shorts:
        sec = estimate_scene_sec(s, channel) + (
            estimate_speech(s.short_hook or "", wpm) if channel.shorts_voice_hook else 0
        )
        if sec > SHORT_MAX_SEC:
            rep.add(
                "error",
                s.id,
                f"шортс ~{sec:.0f} с > {SHORT_MAX_SEC:.0f} с — сократи сцену или сними short_candidate",
            )
        if not s.short_hook:
            rep.add("warning", s.id, "short_candidate без short_hook")

    # по сценам
    for s in script.scenes:
        if count_words(s.narration) > 140:
            rep.add("warning", s.id, "длинная озвучка (>140 слов) — одна идея на сцену")
        if s.type == "diagram":
            err = mermaid_basic_check(s.mermaid)
            if err is None and mermaid_checker is not None:
                err = mermaid_checker(s.mermaid)
            if err:
                rep.add("error", s.id, f"mermaid: {err}")
        elif s.type == "code":
            n = len(s.code.rstrip("\n").splitlines())
            if n > 30:
                rep.add("warning", s.id, f"код {n} строк — на экране будет мелко (≤ 25)")
        elif s.type == "image" and asset_exists is not None and not asset_exists(s.asset_key):
            rep.add("warning", s.id, f"нет ассета {s.asset_key} — положи файл до рендера")
        elif s.type == "terminal":
            if s.mode == "replay" and asset_exists is not None:
                if not (
                    asset_exists(s.replay_output_key) or asset_exists(s.replay_output_key + ".txt")
                ):
                    rep.add("warning", s.id, f"нет файла реального вывода {s.replay_output_key}")
            if s.network:
                rep.add("warning", s.id, "network: true — песочнице дадут сеть")

    # policy песочницы
    rep.violations = policy.check_script(script)
    for v in rep.violations:
        rep.add(v.severity, v.scene_id, f"policy {v.rule}: {v.message}: `{v.command}`")
    return rep
