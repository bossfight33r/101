"""Сбор статистики публикаций. Снимки append-only. YouTube Analytics — опционально."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol

from techstudio.core import log
from techstudio.schemas import Publication, StatsSnapshot

_log = log.get("track")


class Collector(Protocol):
    name: str

    def fetch(self, pubs: list[Publication]) -> list[StatsSnapshot]: ...


class FakeCollector:
    """Детерминированные числа от id публикации; можно задать явно через preset."""

    name = "fake"

    def __init__(self, preset: dict[str, dict] | None = None):
        self.preset = preset or {}

    def fetch(self, pubs: list[Publication]) -> list[StatsSnapshot]:
        now = datetime.now(UTC)
        out = []
        for p in pubs:
            if p.id in self.preset:
                out.append(StatsSnapshot(publication_id=p.id, taken_at=now, **self.preset[p.id]))
                continue
            h = int(hashlib.sha256(p.id.encode()).hexdigest(), 16)
            views = 100 + h % 5000
            out.append(
                StatsSnapshot(
                    publication_id=p.id,
                    taken_at=now,
                    views=views,
                    likes=views // 20,
                    comments=views // 200,
                    avg_view_duration=float(20 + h % 200),
                    avg_view_pct=float(20 + h % 60),
                )
            )
        return out


class YouTubeCollector:
    """Data API: просмотры/лайки/комментарии. Analytics API: средний просмотр, удержание, доход."""

    name = "youtube"

    def __init__(
        self,
        token: Path | None = None,
        with_analytics: bool = True,
        monetized: bool = False,
        yt=None,
        ya=None,
    ):
        """yt/ya — готовые клиенты (тесты). Иначе строим со статической discovery (без сети)."""
        if yt is None:
            from googleapiclient.discovery import build

            from techstudio.publish.youtube import load_credentials

            creds = load_credentials(token)
            yt = build("youtube", "v3", credentials=creds, static_discovery=True)
            if with_analytics:
                ya = build("youtubeAnalytics", "v2", credentials=creds, static_discovery=True)
        self.yt = yt
        self.ya = ya if with_analytics else None
        self.monetized = monetized

    def _analytics(self, video_id: str, start: date) -> dict:
        metrics = "averageViewDuration,averageViewPercentage" + (
            ",estimatedRevenue" if self.monetized else ""
        )
        resp = (
            self.ya.reports()
            .query(
                ids="channel==MINE",
                startDate=start.isoformat(),
                endDate=date.today().isoformat(),
                metrics=metrics,
                filters=f"video=={video_id}",
            )
            .execute()
        )
        rows = resp.get("rows") or []
        if not rows:
            return {}
        row = rows[0]
        out = {"avg_view_duration": float(row[0]), "avg_view_pct": float(row[1])}
        if self.monetized and len(row) > 2:
            out["revenue"] = float(row[2])
        return out

    def fetch(self, pubs: list[Publication]) -> list[StatsSnapshot]:
        ids = [p.remote_id for p in pubs if p.remote_id]
        by_remote = {p.remote_id: p for p in pubs if p.remote_id}
        now = datetime.now(UTC)
        out = []
        for i in range(0, len(ids), 50):
            resp = self.yt.videos().list(part="statistics", id=",".join(ids[i : i + 50])).execute()
            for item in resp.get("items", []):
                st = item.get("statistics", {})
                p = by_remote[item["id"]]
                extra = {}
                if self.ya is not None:
                    try:
                        extra = self._analytics(item["id"], p.scheduled_at.date())
                    except Exception as e:  # noqa: BLE001 — аналитика опциональна
                        _log.warning("analytics.failed", video=item["id"], error=type(e).__name__)
                out.append(
                    StatsSnapshot(
                        publication_id=p.id,
                        taken_at=now,
                        views=int(st.get("viewCount", 0)),
                        likes=int(st.get("likeCount", 0)),
                        comments=int(st.get("commentCount", 0)),
                        **extra,
                    )
                )
        return out


def collect(svc, now: datetime | None = None) -> int:
    from techstudio.pipeline.publish import mark_published

    mark_published(svc, now)
    pubs = [p for p in svc.db.list_publications() if p.status == "published" and p.remote_id]
    if not pubs:
        return 0
    taken = now or datetime.now(UTC)
    snaps = svc.collector.fetch(pubs)
    for s in snaps:
        svc.db.add_snapshot(s.model_copy(update={"taken_at": taken}))
    return len(snaps)
