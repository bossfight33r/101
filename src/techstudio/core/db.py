"""SQLite: темы, видео, переходы статусов, действия ревью, публикации, снимки статистики."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from techstudio.schemas import (
    FailureInfo,
    Publication,
    StatsSnapshot,
    Topic,
    TopicStatus,
    VideoRecord,
    VideoStatus,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    id TEXT PRIMARY KEY, status TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY, topic_id TEXT NOT NULL, channel_id TEXT NOT NULL, status TEXT NOT NULL,
    script_version INTEGER NOT NULL DEFAULT 0, approved_version INTEGER,
    final_approved INTEGER NOT NULL DEFAULT 0, thumbnail_id TEXT, failure TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS video_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT NOT NULL, ts TEXT NOT NULL,
    from_status TEXT, to_status TEXT NOT NULL, note TEXT
);
CREATE TABLE IF NOT EXISTS review_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT NOT NULL, ts TEXT NOT NULL,
    gate TEXT NOT NULL, action TEXT NOT NULL, payload TEXT
);
CREATE TABLE IF NOT EXISTS publications (
    id TEXT PRIMARY KEY, video_id TEXT NOT NULL, kind TEXT NOT NULL, scheduled_at TEXT NOT NULL,
    status TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stats_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT, publication_id TEXT NOT NULL, taken_at TEXT NOT NULL,
    data TEXT NOT NULL
);
"""


def now() -> datetime:
    return datetime.now(UTC)


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def backup(self, dest: Path) -> Path:
        """Онлайн-копия SQLite (консистентна даже во время работы бота)."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(self.path)
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return dest

    # ----- topics -----
    def upsert_topic(self, topic: Topic) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO topics(id, status, data, created_at) VALUES(?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET status=excluded.status, data=excluded.data",
                (topic.id, topic.status.value, topic.model_dump_json(), now().isoformat()),
            )

    def get_topic(self, topic_id: str) -> Topic | None:
        with self._conn() as c:
            row = c.execute("SELECT data FROM topics WHERE id=?", (topic_id,)).fetchone()
        return Topic.model_validate_json(row["data"]) if row else None

    def list_topics(self, status: TopicStatus | None = None) -> list[Topic]:
        q, args = "SELECT data FROM topics", ()
        if status:
            q, args = q + " WHERE status=?", (status.value,)
        with self._conn() as c:
            rows = c.execute(q + " ORDER BY created_at, id", args).fetchall()
        return [Topic.model_validate_json(r["data"]) for r in rows]

    def set_topic_status(self, topic_id: str, status: TopicStatus) -> None:
        topic = self.get_topic(topic_id)
        if topic is None:
            raise KeyError(topic_id)
        self.upsert_topic(topic.model_copy(update={"status": status}))

    # ----- videos -----
    def create_video(self, video_id: str, topic_id: str, channel_id: str) -> VideoRecord:
        ts = now()
        rec = VideoRecord(
            id=video_id, topic_id=topic_id, channel_id=channel_id, created_at=ts, updated_at=ts
        )
        with self._conn() as c:
            c.execute(
                "INSERT INTO videos(id, topic_id, channel_id, status, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?)",
                (video_id, topic_id, channel_id, rec.status.value, ts.isoformat(), ts.isoformat()),
            )
            c.execute(
                "INSERT INTO video_events(video_id, ts, from_status, to_status) VALUES(?,?,?,?)",
                (video_id, ts.isoformat(), None, rec.status.value),
            )
        return rec

    def get_video(self, video_id: str) -> VideoRecord | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
        return self._video(row) if row else None

    def require_video(self, video_id: str) -> VideoRecord:
        rec = self.get_video(video_id)
        if rec is None:
            raise KeyError(f"видео {video_id} не найдено")
        return rec

    def list_videos(self, status: VideoStatus | None = None) -> list[VideoRecord]:
        q, args = "SELECT * FROM videos", ()
        if status:
            q, args = q + " WHERE status=?", (status.value,)
        with self._conn() as c:
            rows = c.execute(q + " ORDER BY created_at", args).fetchall()
        return [self._video(r) for r in rows]

    @staticmethod
    def _video(row: sqlite3.Row) -> VideoRecord:
        return VideoRecord(
            id=row["id"],
            topic_id=row["topic_id"],
            channel_id=row["channel_id"],
            status=VideoStatus(row["status"]),
            script_version=row["script_version"],
            approved_version=row["approved_version"],
            final_approved=bool(row["final_approved"]),
            thumbnail_id=row["thumbnail_id"],
            failure=FailureInfo.model_validate_json(row["failure"]) if row["failure"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def update_video(self, video_id: str, **fields) -> VideoRecord:
        current = self.require_video(video_id)
        allowed = {
            "status",
            "script_version",
            "approved_version",
            "final_approved",
            "thumbnail_id",
            "failure",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"неизвестные поля: {unknown}")
        values = {}
        for key, val in fields.items():
            if key == "status":
                val = VideoStatus(val).value
            elif key == "failure":
                val = val.model_dump_json() if val is not None else None
            elif key == "final_approved":
                val = int(bool(val))
            values[key] = val
        ts = now().isoformat()
        sets = ", ".join(f"{k}=?" for k in values) + ", updated_at=?"
        with self._conn() as c:
            c.execute(f"UPDATE videos SET {sets} WHERE id=?", (*values.values(), ts, video_id))  # noqa: S608
            if "status" in values and values["status"] != current.status.value:
                c.execute(
                    "INSERT INTO video_events(video_id, ts, from_status, to_status) "
                    "VALUES(?,?,?,?)",
                    (video_id, ts, current.status.value, values["status"]),
                )
        return self.require_video(video_id)

    def video_events(self, video_id: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT ts, from_status, to_status, note FROM video_events WHERE video_id=? "
                "ORDER BY id",
                (video_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ----- review -----
    def add_review_action(
        self, video_id: str, gate: str, action: str, payload: dict | None = None
    ) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO review_actions(video_id, ts, gate, action, payload) VALUES(?,?,?,?,?)",
                (video_id, now().isoformat(), gate, action, json.dumps(payload or {})),
            )

    def review_actions(self, video_id: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT ts, gate, action, payload FROM review_actions WHERE video_id=? ORDER BY id",
                (video_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ----- publications -----
    def upsert_publication(self, pub: Publication) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO publications(id, video_id, kind, scheduled_at, status, data) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET scheduled_at=excluded.scheduled_at, "
                "status=excluded.status, data=excluded.data",
                (
                    pub.id,
                    pub.video_id,
                    pub.kind,
                    pub.scheduled_at.isoformat(),
                    pub.status,
                    pub.model_dump_json(),
                ),
            )

    def list_publications(self, video_id: str | None = None) -> list[Publication]:
        q, args = "SELECT data FROM publications", ()
        if video_id:
            q, args = q + " WHERE video_id=?", (video_id,)
        with self._conn() as c:
            rows = c.execute(q + " ORDER BY scheduled_at", args).fetchall()
        return [Publication.model_validate_json(r["data"]) for r in rows]

    # ----- stats -----
    def add_snapshot(self, snap: StatsSnapshot) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO stats_snapshots(publication_id, taken_at, data) VALUES(?,?,?)",
                (snap.publication_id, snap.taken_at.isoformat(), snap.model_dump_json()),
            )

    def latest_snapshots(self) -> dict[str, StatsSnapshot]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT s.data FROM stats_snapshots s JOIN ("
                " SELECT publication_id, MAX(id) AS mid FROM stats_snapshots GROUP BY publication_id"
                ") m ON s.id = m.mid"
            ).fetchall()
        snaps = [StatsSnapshot.model_validate_json(r["data"]) for r in rows]
        return {s.publication_id: s for s in snaps}

    def count_snapshots(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM stats_snapshots").fetchone()[0]
