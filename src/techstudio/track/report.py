"""Отчёт: какие темы, типы сцен и хуки работают лучше. Рекомендации — в файл для ручного ревью."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from techstudio.pipeline import scripts
from techstudio.timing import count_words


@dataclass
class Row:
    key: str
    n: int = 0
    views: float = 0
    pct_sum: float = 0
    pct_n: int = 0
    revenue: float = 0
    vpd_sum: float = 0  # просмотры в день с публикации (честно к свежим видео)
    vpd_w: float = 0

    def add(
        self,
        views: float,
        pct: float | None,
        revenue: float | None,
        weight: float = 1.0,
        days: float = 1.0,
    ) -> None:
        self.n += 1
        self.views += views * weight
        self.vpd_sum += views / max(days, 1.0) * weight
        self.vpd_w += weight
        if pct is not None:
            self.pct_sum += pct * weight
            self.pct_n += weight
        self.revenue += (revenue or 0) * weight

    @property
    def avg_pct(self) -> float | None:
        return self.pct_sum / self.pct_n if self.pct_n else None

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "n": self.n,
            "views": round(self.views),
            "avg_view_pct": round(self.avg_pct, 1) if self.avg_pct is not None else None,
            "revenue": round(self.revenue, 2),
            "views_per_day": round(self.vpd_sum / self.vpd_w, 1) if self.vpd_w else 0,
        }


@dataclass
class Report:
    topics: list[dict] = field(default_factory=list)
    scene_types_long: list[dict] = field(default_factory=list)
    scene_types_shorts: list[dict] = field(default_factory=list)
    hooks_long: list[dict] = field(default_factory=list)
    hooks_shorts: list[dict] = field(default_factory=list)
    totals: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return self.__dict__


def _sorted(rows: dict[str, Row]) -> list[dict]:
    return sorted(
        (r.as_dict() for r in rows.values()),
        key=lambda r: (r["avg_view_pct"] or 0, r["views"]),
        reverse=True,
    )


def published_script(svc, video_id: str, rec):
    """Сценарий той версии, что ушла в публикацию (одобренной), а не последней правки."""
    from techstudio.script import io

    if rec is not None and rec.approved_version:
        path = scripts.version_path(svc, video_id, rec.approved_version)
        if path.exists():
            return io.load(path)
    try:
        return scripts.load_script(svc, video_id)
    except Exception:  # noqa: BLE001 — видео без сценария пропускаем
        return None


def build_report(svc) -> Report:
    snaps = svc.db.latest_snapshots()
    topics: dict[str, Row] = {}
    long_types: dict[str, Row] = {}
    short_types: dict[str, Row] = {}
    hooks_long, hooks_shorts = [], []
    totals = defaultdict(float)
    for pub in svc.db.list_publications():
        snap = snaps.get(pub.id)
        if snap is None:
            continue
        rec = svc.db.get_video(pub.video_id)
        script = published_script(svc, pub.video_id, rec)
        if script is None:
            continue
        days = (snap.taken_at - pub.scheduled_at).total_seconds() / 86400
        totals[f"{pub.kind}_views"] += snap.views
        totals["revenue"] += snap.revenue or 0
        if pub.kind == "long":
            topic = svc.db.get_topic(rec.topic_id) if rec else None
            key = topic.title if topic else pub.video_id
            topics.setdefault(key, Row(key)).add(
                snap.views, snap.avg_view_pct, snap.revenue, days=days
            )
            weights = defaultdict(float)
            for s in script.scenes:
                weights[s.type] += max(count_words(s.narration), 1)
            total = sum(weights.values())
            for t, w in weights.items():
                long_types.setdefault(t, Row(t)).add(
                    snap.views, snap.avg_view_pct, snap.revenue, w / total, days=days
                )
            hooks_long.append(
                {
                    "hook": script.hook,
                    "words": count_words(script.hook),
                    "views": snap.views,
                    "avg_view_pct": snap.avg_view_pct,
                }
            )
        else:
            scene_id = (pub.short_id or "").removeprefix("short-")
            scene = next((s for s in script.scenes if s.id == scene_id), None)
            if scene is None:
                continue
            short_types.setdefault(scene.type, Row(scene.type)).add(
                snap.views, snap.avg_view_pct, snap.revenue, days=days
            )
            hooks_shorts.append(
                {
                    "hook": scene.short_hook or "",
                    "scene_type": scene.type,
                    "views": snap.views,
                    "avg_view_pct": snap.avg_view_pct,
                }
            )
    key = lambda h: (h["avg_view_pct"] or 0, h["views"])  # noqa: E731
    return Report(
        topics=_sorted(topics),
        scene_types_long=_sorted(long_types),
        scene_types_shorts=_sorted(short_types),
        hooks_long=sorted(hooks_long, key=key, reverse=True),
        hooks_shorts=sorted(hooks_shorts, key=lambda h: h["views"], reverse=True),
        totals={k: round(v, 2) for k, v in totals.items()},
    )


def to_text(rep: Report) -> str:
    def table(title: str, rows: list[dict]) -> list[str]:
        out = [f"## {title}"]
        if not rows:
            return out + ["нет данных", ""]
        for r in rows:
            pct = "—" if r["avg_view_pct"] is None else f"{r['avg_view_pct']}%"
            out.append(
                f"- {r['key']}: удержание {pct}, просмотры {r['views']} ({r['views_per_day']}/день), видео {r['n']}"
                + (f", доход {r['revenue']}" if r["revenue"] else "")
            )
        return out + [""]

    lines = ["# TechStudio — отчёт", ""]
    lines += table("Темы (длинные видео)", rep.topics)
    lines += table("Типы сцен в длинных (взвешено по объёму текста)", rep.scene_types_long)
    lines += table("Типы сцен в шортсах", rep.scene_types_shorts)
    lines.append("## Хуки длинных (лучшие сверху)")
    lines += [
        f"- {h['avg_view_pct']}% / {h['views']} просм. ({h['words']} слов): {h['hook']}"
        for h in rep.hooks_long[:5]
    ] or ["нет данных"]
    lines += ["", "## Хуки шортсов (по просмотрам)"]
    lines += [
        f"- {h['views']} просм. [{h['scene_type']}]: {h['hook']}" for h in rep.hooks_shorts[:5]
    ] or ["нет данных"]
    return "\n".join(lines) + "\n"


def recommendations(rep: Report) -> str:
    """Наблюдения + предложения к промпту. Только для ручного ревью: production-промпты не меняются."""
    lines = [
        f"# Рекомендации TechStudio — {datetime.now(UTC):%Y-%m-%d}",
        "",
        "Файл для ручного ревью. Промпты автоматически не меняются.",
        "",
    ]
    if not (rep.topics or rep.scene_types_shorts):
        return (
            "\n".join(
                lines
                + ["Пока мало данных: нужны опубликованные видео со статистикой (studio track)."]
            )
            + "\n"
        )
    if rep.scene_types_long:
        best, worst = rep.scene_types_long[0], rep.scene_types_long[-1]
        lines.append(
            f"- В длинных лучше удерживают видео с бо́льшей долей сцен `{best['key']}`; меньше — `{worst['key']}`."
        )
    if rep.scene_types_shorts:
        lines.append(
            f"- Шортсы из сцен `{rep.scene_types_shorts[0]['key']}` набирают лучше остальных."
        )
    if rep.topics:
        lines.append(
            f"- Лучшая тема по удержанию: «{rep.topics[0]['key']}». Похожие темы — кандидаты в бэклог."
        )
    if len(rep.hooks_long) >= 2:
        top = rep.hooks_long[: max(1, len(rep.hooks_long) // 2)]
        bottom = rep.hooks_long[len(top) :]
        avg = lambda xs: sum(h["words"] for h in xs) / len(xs)  # noqa: E731
        if bottom:
            lines.append(
                f"- Средняя длина лучших хуков {avg(top):.0f} слов против {avg(bottom):.0f} у худших."
            )
    lines += ["", "## Предложения к prompts/script.md (применять вручную)"]
    if rep.scene_types_long:
        lines.append(f"- Чаще выбирать `{rep.scene_types_long[0]['key']}` для ключевых шагов.")
    if rep.hooks_long:
        lines.append(f"- Ориентир для хука: «{rep.hooks_long[0]['hook']}»")
    return "\n".join(lines) + "\n"
