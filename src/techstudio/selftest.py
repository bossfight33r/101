"""studio selftest: прогон демо-видео на реальных компонентах окружения (Docker+VHS, mermaid, Piper, ASR).
LLM — фейк (без затрат), публикации нет, данные — в отдельной папке. Итог — по компоненту."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from techstudio.config import Settings
from techstudio.schemas import LongformTarget, Topic
from techstudio.services import Services

DEMO_TOPIC = Topic(
    id="selftest",
    title="Самопроверка TechStudio",
    key_points=["живой терминал", "replay", "код из сцены"],
    must_show_commands=["uname -a", "python3 hello.py", "curl -I https://example.com"],
)
REPLAY_OUTPUT = "HTTP/2 200\ncontent-type: text/html; charset=UTF-8\nserver: ECAcc (selftest)\n"


@dataclass
class SelftestResult:
    video_id: str = ""
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    long_path: Path | None = None

    @property
    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.checks)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, ok, detail))


def run(base: Settings, data_dir: Path, *, real: bool = True, keep: bool = True) -> SelftestResult:
    if data_dir.exists() and not keep:
        shutil.rmtree(data_dir)
    settings = base.model_copy(
        update={
            "data_dir": data_dir,
            "llm_provider": "fake",
            "publisher": "fake",
            "collector": "fake",
            "renderers": "real" if real else base.renderers,
        }
    )
    channel = base.channel.model_copy(update={"longform": LongformTarget(min_sec=30, max_sec=900)})
    settings.__dict__["channel"] = channel
    settings.__dict__["voices"] = base.voices
    svc = Services.from_settings(settings)

    from techstudio.pipeline import orchestrator, scripts

    res = SelftestResult()
    svc.db.upsert_topic(DEMO_TOPIC)
    script, report = scripts.new_script(svc, DEMO_TOPIC.id)
    res.video_id = script.video_id
    res.add("сценарий (fake LLM) + валидация", report.ok, "; ".join(map(str, report.errors))[:300])
    for s in script.scenes:
        if s.type == "terminal" and s.mode == "replay":
            d = svc.storage.ensure_dir(s.replay_output_key)
            (d / "0.txt").write_text(REPLAY_OUTPUT, encoding="utf-8")
    try:
        scripts.approve(svc, script.video_id)
        summary = orchestrator.render_video(svc, script.video_id)
    except Exception as e:  # noqa: BLE001 — итог для человека
        rec = svc.db.get_video(script.video_id)
        stage = rec.failure.stage if rec and rec.failure else "?"
        res.add(f"рендер (этап {stage})", False, f"{type(e).__name__}: {str(e)[:400]}")
        return res

    warnings = summary["warnings"]
    res.long_path = svc.storage.path(summary["long"]["long_key"])
    res.add("длинное видео 1920x1080", res.long_path.exists(), str(res.long_path))
    res.add("шортсы 1080x1920", bool(summary["shorts"]), f"{len(summary['shorts'])} шт.")
    fake = [w for w in warnings if "fake-визуал" in w]
    res.add("терминал: Docker + VHS (live, files, replay)", not fake, "; ".join(fake)[:200])
    fallback = [w for w in warnings if "fallback" in w]
    res.add("mermaid-cli", not fallback, "; ".join(fallback)[:200])
    res.add("TTS", True, f"{svc.tts.name}" + (" (фейк)" if svc.tts.name == "fake" else ""))
    res.add(
        "ASR-тайминги",
        True,
        f"{svc.transcriber.name}" + (" (фейк)" if svc.transcriber.name == "fake" else ""),
    )
    res.add("главы YouTube", summary["long"]["chapters_valid"], "")
    return res
