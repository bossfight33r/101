"""Настройки из env (TS_*) + YAML канала, тем и голосов."""

from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from techstudio.schemas import Channel, Topic

ROOT = Path(__file__).resolve().parents[2]


class VoiceConfig(BaseModel):
    engine: Literal["piper", "fake"] = "piper"
    model: str = ""
    speaker: int | None = None
    length_scale: float = 1.0
    sentence_silence: float = 0.25


class VoicesFile(BaseModel):
    default: str
    voices: dict[str, VoiceConfig]
    pronunciation: dict[str, str] = Field(default_factory=dict)

    def voice(self, voice_id: str) -> VoiceConfig:
        if voice_id not in self.voices:
            raise KeyError(f"голос {voice_id!r} не найден в voices.yaml")
        return self.voices[voice_id]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TS_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data/studio")
    channel_file: Path = Path("config/studio/channel.yaml")
    topics_file: Path = Path("config/studio/topics.yaml")
    voices_file: Path = Path("config/studio/voices.yaml")

    llm_provider: Literal["anthropic", "fake"] = "anthropic"
    llm_model: str = "claude-opus-5-5"
    llm_max_tokens: int = 16000
    tts: Literal["piper", "fake"] = "piper"
    piper_bin: str = "piper"
    transcriber: Literal["faster_whisper", "mlx", "fake"] = "faster_whisper"
    whisper_model: str = "large-v3-turbo"
    renderers: Literal["auto", "real", "fake"] = "auto"
    encoder: str = "auto"

    docker_bin: str = "docker"
    sandbox_image: str = "techstudio-sandbox:latest"
    vhs_bin: str = "vhs"  # локальный vhs — только для `vhs validate` tape, команды не выполняет
    sandbox_cpus: float = 1.0
    sandbox_memory: str = "1g"
    sandbox_pids: int = 256
    sandbox_timeout: int = 300
    mermaid_image: str = "minlag/mermaid-cli:latest"
    mermaid_bin: str = "mmdc"
    mermaid_puppeteer_config: str | None = (
        None  # JSON для mmdc -p (executablePath, --no-sandbox под root)
    )

    publisher: Literal["youtube", "fake"] = "youtube"
    collector: Literal["youtube", "fake"] = "youtube"
    monetized: bool = False  # доход из YouTube Analytics (только монетизированный канал)
    youtube_client_secrets: Path = Path("data/studio/secrets/youtube_client_secret.json")

    admin_ids: str = ""
    telegram_bot_token: SecretStr | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    anthropic_api_key: SecretStr | None = Field(default=None, alias="ANTHROPIC_API_KEY")

    pause_before: float = 0.3
    pause_after: float = 0.5

    @property
    def admin_id_set(self) -> set[int]:
        return {int(x) for x in self.admin_ids.replace(" ", "").split(",") if x}

    def resolve(self, p: Path) -> Path:
        return p if p.is_absolute() else Path.cwd() / p

    @cached_property
    def channel(self) -> Channel:
        return load_channel(_with_example(self.resolve(self.channel_file)))

    @cached_property
    def voices(self) -> VoicesFile:
        return load_voices(_with_example(self.resolve(self.voices_file)))


def _with_example(path: Path) -> Path:
    """channel.yaml нет — берём channel.example.yaml рядом (или из репо)."""
    if path.exists():
        return path
    example = path.with_name(path.stem + ".example" + path.suffix)
    if example.exists():
        return example
    repo_example = ROOT / "config" / "studio" / example.name
    if repo_example.exists():
        return repo_example
    repo_file = ROOT / "config" / "studio" / path.name
    return repo_file


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_channel(path: Path) -> Channel:
    return Channel.model_validate(_load_yaml(path))


def load_voices(path: Path) -> VoicesFile:
    return VoicesFile.model_validate(_load_yaml(path))


def load_topics(path: Path) -> list[Topic]:
    data = _load_yaml(path)
    return [Topic.model_validate(t) for t in data.get("topics", [])]
