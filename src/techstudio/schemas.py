"""Контракты TechStudio. Данные между этапами — только через эти модели."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------- общие (в ClipFactory жили бы в его schemas; здесь — в одном месте) ----------


class Word(BaseModel):
    text: str
    start: float
    end: float
    prob: float = 1.0


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- канал ----------


class DailyLimits(Strict):
    long: int = Field(1, ge=0)
    shorts: int = Field(3, ge=0)


class ChannelStyle(Strict):
    bg: str = "#0f172a"
    fg: str = "#e2e8f0"
    accent: str = "#22d3ee"
    muted: str = "#94a3b8"
    highlight_bg: str = "#334155"
    font: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font_bold: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    mono_font: str = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
    caption_font_name: str = ""  # пусто — семейство берётся из файла font
    code_theme: str = "monokai"
    terminal_theme: str = "Dracula"


class LongformTarget(Strict):
    min_sec: int = 360
    max_sec: int = 720


class ScheduleConfig(Strict):
    timezone: str = "Europe/Moscow"
    long_time: str = "18:00"  # HH:MM, локальное время канала
    shorts_interval_hours: float = Field(4.0, gt=0)


class Channel(Strict):
    id: str
    name: str
    language: str = "ru"
    voice_id: str
    default_tags: list[str] = Field(default_factory=list)
    description_footer: str = ""
    daily_limits: DailyLimits = Field(default_factory=DailyLimits)
    account_id: str
    style: ChannelStyle = Field(default_factory=ChannelStyle)
    longform: LongformTarget = Field(default_factory=LongformTarget)
    words_per_minute: int = Field(140, ge=60, le=260)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    music_tracks: list[str] = Field(default_factory=list)  # только собственные треки
    music_volume: float = Field(0.12, ge=0, le=1)
    transition: Literal["cut", "fade"] = "cut"
    shorts_voice_hook: bool = True
    short_candidates_min: int = 3
    short_candidates_max: int = 5


# ---------- темы ----------


class AudienceLevel(StrEnum):
    beginner = "beginner"
    intermediate = "intermediate"
    advanced = "advanced"


class TopicStatus(StrEnum):
    backlog = "backlog"
    in_progress = "in_progress"
    done = "done"
    rejected = "rejected"


class Topic(Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    title: str
    audience_level: AudienceLevel = AudienceLevel.beginner
    key_points: list[str] = Field(default_factory=list)
    must_show_commands: list[str] = Field(default_factory=list)
    notes: str = ""
    status: TopicStatus = TopicStatus.backlog


# ---------- сценарий ----------

SceneId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$")]


class SceneBase(Strict):
    id: SceneId
    narration: str = Field(min_length=1)
    min_sec: float = Field(0, ge=0)
    short_candidate: bool = False
    short_hook: str | None = None
    chapter: str | None = None  # заголовок главы YouTube, если сцена начинает главу


FILE_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,63}")

# ключи ассетов из сценария (его пишет LLM): только внутри data/studio/assets/, без .. и абсолютных путей
ASSET_KEY = re.compile(r"assets/(?:[A-Za-z0-9_][A-Za-z0-9._-]*/)*[A-Za-z0-9_][A-Za-z0-9._-]*")


def _check_asset_key(value: str | None) -> str | None:
    if value is not None and (not ASSET_KEY.fullmatch(value) or ".." in value.split("/")):
        raise ValueError(f"ключ {value!r}: только assets/… без .. и абсолютных путей")
    return value


AssetKey = Annotated[str, AfterValidator(_check_asset_key)]


class TerminalScene(SceneBase):
    type: Literal["terminal"] = "terminal"
    mode: Literal["live", "replay"] = "live"
    commands: list[str] = Field(min_length=1)
    replay_output_key: AssetKey | None = None
    network: bool = False
    typing_speed: int = Field(45, ge=5, le=300)  # мс на символ
    # файлы в ~ контейнера до команд: имя файла -> id code-сцены этого сценария (код видит зритель)
    files: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _replay_needs_output(self):
        for name in self.files:
            if not FILE_NAME.fullmatch(name):
                raise ValueError(f"имя файла {name!r}: только [A-Za-z0-9._-], без папок")
        if self.mode == "replay" and self.files:
            raise ValueError("files только для mode=live: в replay команды не выполняются")
        if self.mode == "replay" and not self.replay_output_key:
            raise ValueError("mode=replay требует replay_output_key (файл с реальным выводом)")
        if self.mode == "replay" and self.network:
            raise ValueError("network не имеет смысла для replay: команды не выполняются")
        return self


class CodeScene(SceneBase):
    type: Literal["code"] = "code"
    language: str
    code: str = Field(min_length=1)
    highlight_lines: list[int] = Field(default_factory=list)
    reveal: Literal["all", "by_line"] = "all"

    @model_validator(mode="after")
    def _lines_in_range(self):
        n = len(self.code.rstrip("\n").splitlines())
        bad = [i for i in self.highlight_lines if i < 1 or i > n]
        if bad:
            raise ValueError(f"highlight_lines вне диапазона 1..{n}: {bad}")
        return self


class DiagramScene(SceneBase):
    type: Literal["diagram"] = "diagram"
    mermaid: str = Field(min_length=1)


class SlideScene(SceneBase):
    type: Literal["slide"] = "slide"
    title: str
    bullets: list[str] = Field(default_factory=list, max_length=4)


class ImageScene(SceneBase):
    type: Literal["image"] = "image"
    asset_key: AssetKey
    caption: str = ""


Scene = Annotated[
    TerminalScene | CodeScene | DiagramScene | SlideScene | ImageScene,
    Field(discriminator="type"),
]
SCENE_TYPES = ("terminal", "code", "diagram", "slide", "image")


class Script(Strict):
    video_id: str
    topic_id: str
    version: int = Field(1, ge=1)
    title: str
    hook: str = Field(min_length=1)
    scenes: list[Scene] = Field(min_length=1)
    outro: str = ""

    @field_validator("scenes")
    @classmethod
    def _unique_ids(cls, scenes):
        ids = [s.id for s in scenes]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ValueError(f"повторяющиеся id сцен: {sorted(dup)}")
        reserved = {"hook", "outro"} & set(ids)
        if reserved:
            raise ValueError(f"id {sorted(reserved)} зарезервированы")
        code_ids = {s.id for s in scenes if s.type == "code"}
        for s in scenes:
            for name, src in getattr(s, "files", {}).items():
                if src not in code_ids:
                    raise ValueError(
                        f"{s.id}: files.{name} ссылается на {src!r} — нужна code-сцена"
                    )
        return scenes

    def files_for(self, scene) -> dict[str, str]:
        """{имя файла: код} для terminal-сцены."""
        return {name: self.scene(src).code for name, src in getattr(scene, "files", {}).items()}

    def scene(self, scene_id: str):
        for s in self.scenes:
            if s.id == scene_id:
                return s
        raise KeyError(scene_id)


# ---------- артефакты этапов ----------

Aspect = Literal["16x9", "9x16"]
ASPECT_SIZE: dict[str, tuple[int, int]] = {"16x9": (1920, 1080), "9x16": (1080, 1920)}


class NarrationAudio(BaseModel):
    scene_id: str
    audio_key: str
    duration: float
    words: list[Word]


class SceneRender(BaseModel):
    scene_id: str
    aspect: Aspect
    video_key: str
    duration: float
    warnings: list[str] = Field(default_factory=list)  # видно на ревью (fallback и т.п.)


class Chapter(BaseModel):
    start: float
    title: str


class VideoAssembly(BaseModel):
    video_id: str
    long_key: str
    captions_key: str
    chapters: list[Chapter]
    duration: float
    chapters_valid: bool = True


class ShortSpec(BaseModel):
    id: str
    scene_ids: list[str]
    hook: str | None = None
    duration: float
    video_key: str | None = None


class ThumbnailVariant(BaseModel):
    id: str
    image_key: str
    text: str


class VideoMeta(BaseModel):
    title: str = Field(max_length=100)
    description: str
    tags: list[str] = Field(default_factory=list)
    thumbnail_texts: list[str] = Field(default_factory=list)


# ---------- статусы ----------


class VideoStatus(StrEnum):
    draft = "draft"
    script_review = "script_review"
    approved = "approved"
    voicing = "voicing"
    rendering = "rendering"
    assembling = "assembling"
    final_review = "final_review"
    scheduled = "scheduled"
    published = "published"
    failed = "failed"
    rejected = "rejected"


class FailureInfo(BaseModel):
    stage: str
    error_type: str
    message: str
    retryable: bool = True


class VideoRecord(BaseModel):
    id: str
    topic_id: str
    channel_id: str
    status: VideoStatus = VideoStatus.draft
    script_version: int = 0
    approved_version: int | None = None
    final_approved: bool = False
    thumbnail_id: str | None = None
    failure: FailureInfo | None = None
    created_at: datetime
    updated_at: datetime


class Publication(BaseModel):
    id: str
    video_id: str
    kind: Literal["long", "short"]
    short_id: str | None = None
    platform: str = "youtube"
    account_id: str
    scheduled_at: datetime
    status: Literal["planned", "uploaded", "published", "failed"] = "planned"
    remote_id: str | None = None
    url: str | None = None
    notes: list[str] = Field(default_factory=list)


class StatsSnapshot(BaseModel):
    publication_id: str
    taken_at: datetime
    views: int = 0
    likes: int = 0
    comments: int = 0
    avg_view_duration: float | None = None  # секунды
    avg_view_pct: float | None = None  # 0..100
    revenue: float | None = None
