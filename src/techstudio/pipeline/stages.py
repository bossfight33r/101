"""Этапы рендера видео. Каждый этап идемпотентен и кешируется манифестом (ADR 0005)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from techstudio.assemble import chapters as chap
from techstudio.assemble import longform, music, shorts
from techstudio.core import captions, ffmpeg, log, probe
from techstudio.core.encoder import Encoder, select
from techstudio.core.llm import extract_json
from techstudio.core.manifest import Manifest, file_hash, inputs_hash
from techstudio.prompts import load as load_prompt
from techstudio.render.base import RenderEnv
from techstudio.render.registry import build_renderers
from techstudio.render.slide import SlideRenderer
from techstudio.schemas import (
    NarrationAudio,
    SceneRender,
    Script,
    ShortSpec,
    SlideScene,
    ThumbnailVariant,
    VideoAssembly,
    VideoMeta,
    Word,
)
from techstudio.services import Services
from techstudio.thumbnail import render as thumbs
from techstudio.timing import align_words, scene_duration
from techstudio.voice.base import apply_pronunciation

_log = log.get("stages")

VOICE_V = 1
VISUAL_V = 2
SEGMENT_V = 2
LONG_V = 1
SHORT_V = 1
META_V = 1
THUMBS_V = 1
PREVIEW_V = 1


class StageError(RuntimeError):
    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class VideoCtx:
    svc: Services
    script: Script
    vdir: Path
    env: RenderEnv
    encoder: Encoder
    renderers: dict
    long_scenes: list = field(default_factory=list)  # hook + сцены + outro
    narration: dict[str, NarrationAudio] = field(default_factory=dict)
    durations: dict[str, float] = field(default_factory=dict)
    renders: dict[tuple[str, str], SceneRender] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    cache_hits: list[str] = field(default_factory=list)
    ran: list[str] = field(default_factory=list)

    @property
    def video_id(self) -> str:
        return self.script.video_id

    def scene_dir(self, scene_id: str) -> Path:
        return self.env.scene_dir(scene_id)

    def scene_manifest(self, scene_id: str) -> tuple[Manifest, Path]:
        path = self.scene_dir(scene_id) / "manifest.json"
        return Manifest.load(path), path

    def video_manifest(self) -> tuple[Manifest, Path]:
        path = self.vdir / "manifest.json"
        return Manifest.load(path), path


def service_scenes(script: Script, channel_name: str) -> list:
    """Служебные сцены хука и аутро (ADR 0002) + сцены сценария."""
    scenes = [SlideScene(id="hook", narration=script.hook, title=script.title)]
    scenes += list(script.scenes)
    if script.outro.strip():
        scenes.append(
            SlideScene(id="outro", narration=script.outro, title="Что дальше", bullets=[])
        )
    return scenes


def make_ctx(svc: Services, script: Script) -> VideoCtx:
    vdir = svc.video_dir(script.video_id)
    encoder = select(svc.settings.encoder)
    env = RenderEnv(storage=svc.storage, video_dir=vdir, style=svc.channel.style, encoder=encoder)
    ctx = VideoCtx(
        svc=svc,
        script=script,
        vdir=vdir,
        env=env,
        encoder=encoder,
        renderers=build_renderers(svc, env),
    )
    ctx.long_scenes = service_scenes(script, svc.channel.name)
    return ctx


def _hit(ctx: VideoCtx, name: str) -> None:
    ctx.cache_hits.append(name)


# ---------------- voice ----------------


def _voice_one(ctx: VideoCtx, scene_id: str, text: str, stem: str) -> NarrationAudio:
    svc = ctx.svc
    voices = svc.settings.voices
    voice = voices.voice(svc.channel.voice_id)
    tts_text = apply_pronunciation(text, voices.pronunciation)
    sdir = ctx.scene_dir(scene_id)
    m, mpath = ctx.scene_manifest(scene_id)
    stage = f"voice:{stem}"
    ihash = inputs_hash(
        text, tts_text, voice, svc.tts.name, svc.transcriber.name, svc.channel.language
    )
    meta_path = sdir / f"{stem}.json"
    if m.is_fresh(stage, VOICE_V, ihash, sdir) and meta_path.exists():
        _hit(ctx, f"{scene_id}/{stage}")
        return NarrationAudio.model_validate_json(meta_path.read_text(encoding="utf-8"))
    raw = sdir / f"{stem}_raw.wav"
    wav = sdir / f"{stem}.wav"
    svc.tts.synthesize(tts_text, voice, raw)
    # нормализация громкости голоса, 48 кГц моно
    ffmpeg.run(
        [
            "-i",
            str(raw),
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar",
            "48000",
            "-ac",
            "1",
            str(wav),
        ]
    )
    raw.unlink(missing_ok=True)
    duration = probe.probe(wav).duration
    # пословные тайминги — прогоном TTS-аудио через ASR, а не оценкой
    asr = svc.transcriber.transcribe(wav, language=svc.channel.language, hint=tts_text)
    words = align_words(text, asr, duration)
    words_path = sdir / ("words.json" if stem == "narration" else f"{stem}_words.json")
    words_path.write_text(
        json.dumps([w.model_dump() for w in words], ensure_ascii=False), encoding="utf-8"
    )
    na = NarrationAudio(
        scene_id=scene_id, audio_key=svc.storage.key(wav), duration=round(duration, 3), words=words
    )
    meta_path.write_text(na.model_dump_json(), encoding="utf-8")
    m.record(stage, VOICE_V, ihash, sdir, [wav, words_path, meta_path])
    m.save(mpath)
    ctx.ran.append(f"{scene_id}/{stage}")
    return na


def run_voice(ctx: VideoCtx) -> None:
    for scene in ctx.long_scenes:
        ctx.narration[scene.id] = _voice_one(ctx, scene.id, scene.narration, "narration")
    if ctx.svc.channel.shorts_voice_hook:
        for scene in ctx.script.scenes:
            if scene.short_candidate and scene.short_hook:
                ctx.narration[f"{scene.id}#hook"] = _voice_one(
                    ctx, scene.id, scene.short_hook, "short_hook"
                )


# ---------------- visuals ----------------


def _asset_inputs(ctx: VideoCtx, scene) -> list:
    st = ctx.svc.storage
    if scene.type == "image":
        p = st.path(scene.asset_key)
        return [p if p.exists() else f"missing:{scene.asset_key}"]
    if scene.type == "terminal" and scene.mode == "replay":
        base = st.path(scene.replay_output_key)
        files = (
            sorted(base.glob("*.txt"))
            if base.is_dir()
            else [st.path(scene.replay_output_key + ".txt"), base]
        )
        return [p for p in files if p.exists()]
    return []


def compute_durations(ctx: VideoCtx) -> None:
    s = ctx.svc.settings
    for scene in ctx.long_scenes:
        r = ctx.renderers[scene.type]
        ctx.durations[scene.id] = scene_duration(
            ctx.narration[scene.id].duration,
            min_sec=scene.min_sec,
            visual_min=r.min_duration(scene),
            pause_before=s.pause_before,
            pause_after=s.pause_after,
        )


def _render_one(ctx: VideoCtx, scene, aspect: str) -> SceneRender:
    r = ctx.renderers[scene.type]
    target = ctx.durations[scene.id]
    sdir = ctx.scene_dir(scene.id)
    m, mpath = ctx.scene_manifest(scene.id)
    stage = f"visual:{aspect}"
    ihash = inputs_hash(
        scene,
        aspect,
        round(target, 2),
        r.name,
        r.version,
        ctx.svc.channel.style,
        ctx.encoder.name,
        *_asset_inputs(ctx, scene),
    )
    if m.is_fresh(stage, VISUAL_V, ihash, sdir):
        _hit(ctx, f"{scene.id}/{stage}")
        return SceneRender.model_validate(m.stages[stage].extra["render"])
    if scene.id in ("hook", "outro") and isinstance(r, SlideRenderer):
        rendered = r.render(
            scene, aspect, target, subtitle=ctx.svc.channel.name if scene.id == "outro" else ""
        )
    else:
        rendered = r.render(scene, aspect, target)
    raw = ctx.svc.storage.path(rendered.video_key)
    result = rendered
    m.record(stage, VISUAL_V, ihash, sdir, [raw], extra={"render": result.model_dump()})
    m.save(mpath)
    ctx.ran.append(f"{scene.id}/{stage}")
    return result


def run_visuals(ctx: VideoCtx) -> None:
    compute_durations(ctx)
    for scene in ctx.long_scenes:
        ctx.renders[(scene.id, "16x9")] = _render_one(ctx, scene, "16x9")
        # 9:16 нужен только кандидатам в шортсы (ADR 0005)
        if getattr(scene, "short_candidate", False):
            ctx.renders[(scene.id, "9x16")] = _render_one(ctx, scene, "9x16")
    for (sid, aspect), r in ctx.renders.items():
        ctx.warnings += [f"{sid} {aspect}: {w}" for w in r.warnings]


# ---------------- segments ----------------


def _segment(
    ctx: VideoCtx,
    scene_id: str,
    aspect: str,
    narration_stem: str | None = "narration",
    *,
    visual: Path | None = None,
    duration: float | None = None,
    stem: str | None = None,
) -> Path:
    s = ctx.svc.settings
    sdir = ctx.scene_dir(scene_id)
    m, mpath = ctx.scene_manifest(scene_id)
    stem = stem or f"segment_{aspect}"
    out = sdir / f"{stem}.mp4"
    visual_duration = None
    if visual is None:
        rendered = ctx.renders[(scene_id, aspect)]
        visual, visual_duration = ctx.svc.storage.path(rendered.video_key), rendered.duration
    duration = duration if duration is not None else ctx.durations[scene_id]
    audio = sdir / f"{narration_stem}.wav" if narration_stem else None
    fade = ctx.svc.channel.transition == "fade" and aspect == "16x9"
    stage = f"segment:{stem}"
    ihash = inputs_hash(
        visual, audio or "silence", round(duration, 3), s.pause_before, fade, ctx.encoder.name
    )
    if m.is_fresh(stage, SEGMENT_V, ihash, sdir):
        _hit(ctx, f"{scene_id}/{stage}")
        return out
    longform.build_segment(
        visual,
        audio,
        out,
        duration=duration,
        pause_before=s.pause_before,
        encoder=ctx.encoder,
        fade=fade,
        visual_duration=visual_duration,
    )
    m.record(stage, SEGMENT_V, ihash, sdir, [out])
    m.save(mpath)
    ctx.ran.append(f"{scene_id}/{stage}")
    return out


# ---------------- long ----------------


def timed_scenes(ctx: VideoCtx) -> list[chap.TimedScene]:
    out, t = [], 0.0
    for scene in ctx.long_scenes:
        d = ctx.durations[scene.id]
        out.append(chap.TimedScene(scene.id, getattr(scene, "chapter", None), t, d))
        t += d
    return out


def long_words(ctx: VideoCtx) -> list[Word]:
    words: list[Word] = []
    pause = ctx.svc.settings.pause_before
    for ts in timed_scenes(ctx):
        words += captions.shift(ctx.narration[ts.scene_id].words, ts.start + pause)
    return words


def run_long(ctx: VideoCtx) -> VideoAssembly:
    svc, vdir = ctx.svc, ctx.vdir
    segments = [_segment(ctx, sc.id, "16x9") for sc in ctx.long_scenes]
    timed = timed_scenes(ctx)
    total = timed[-1].start + timed[-1].duration
    ch = svc.channel
    track = music.pick_track(
        ch.music_tracks,
        ctx.video_id,
        lambda t: svc.storage.path(t) if not Path(t).is_absolute() else Path(t),
    )
    m, mpath = ctx.video_manifest()
    ihash = inputs_hash(
        *segments,
        track or "no-music",
        ch.music_volume,
        [(t.scene_id, t.chapter, t.duration) for t in timed],
    )
    long_path, srt_path, chapters_path = (
        vdir / "long.mp4",
        vdir / "captions.srt",
        vdir / "chapters.txt",
    )
    asm_path = vdir / "assembly.json"
    if m.is_fresh("long", LONG_V, ihash, vdir) and asm_path.exists():
        _hit(ctx, "long")
        return VideoAssembly.model_validate_json(asm_path.read_text(encoding="utf-8"))
    raw = longform.concat(segments, vdir / "long_raw.mp4")
    longform.finalize_audio(raw, long_path, total=total, track=track, volume=ch.music_volume)
    raw.unlink(missing_ok=True)
    info = probe.validate_video(
        long_path, width=1920, height=1080, expected_duration=total, tolerance=1.0, need_audio=True
    )
    srt_path.write_text(captions.to_srt(long_words(ctx)), encoding="utf-8")
    chapters = chap.build_chapters(timed)
    ok, reason = chap.validate_chapters(chapters, info.duration)
    if not ok:
        ctx.warnings.append(f"главы: {reason}")
    chapters_path.write_text(chap.to_text(chapters, info.duration), encoding="utf-8")
    asm = VideoAssembly(
        video_id=ctx.video_id,
        long_key=svc.storage.key(long_path),
        captions_key=svc.storage.key(srt_path),
        chapters=chapters,
        duration=round(info.duration, 3),
        chapters_valid=ok,
    )
    asm_path.write_text(asm.model_dump_json(indent=2), encoding="utf-8")
    m.record("long", LONG_V, ihash, vdir, [long_path, srt_path, chapters_path, asm_path])
    m.save(mpath)
    ctx.ran.append("long")
    return asm


# ---------------- shorts ----------------


def _card(
    ctx: VideoCtx, scene_id: str, stem: str, title: str, subtitle: str, duration: float
) -> Path:
    """Карточка 9:16 (хук шортса / end-card) — кадры слайда, кеш через сегмент."""
    slide = SlideScene(id=scene_id, narration="-", title=title)
    sdir = ctx.scene_dir(scene_id)
    out = sdir / f"{stem}_card.mp4"
    m, mpath = ctx.scene_manifest(scene_id)
    stage = f"card:{stem}"
    ihash = inputs_hash(
        title, subtitle, round(duration, 3), ctx.svc.channel.style, ctx.encoder.name
    )
    if m.is_fresh(stage, SEGMENT_V, ihash, sdir):
        return out
    from techstudio.render.base import frames_to_video
    from techstudio.render.slide import compose

    png = compose(slide, "9x16", ctx.env, 0, sdir / f"{stem}_card.png", subtitle)
    frames_to_video([(png, duration)], out, "9x16", ctx.encoder)
    m.record(stage, SEGMENT_V, ihash, sdir, [out])
    m.save(mpath)
    return out


def run_shorts(ctx: VideoCtx) -> list[ShortSpec]:
    svc, ch = ctx.svc, ctx.svc.channel
    pause = svc.settings.pause_before
    specs: list[ShortSpec] = []
    for scene in ctx.script.scenes:
        if not scene.short_candidate:
            continue
        sid = f"short-{scene.id}"
        hook_na = ctx.narration.get(f"{scene.id}#hook")
        parts: list[Path] = []
        words: list[Word] = []
        t = 0.0
        if hook_na is not None:
            hook_dur = round(hook_na.duration + pause + 0.3, 3)
            card = _card(ctx, scene.id, "short_hook", scene.short_hook, "", hook_dur)
            parts.append(
                _segment(
                    ctx,
                    scene.id,
                    "9x16",
                    "short_hook",
                    visual=card,
                    duration=hook_dur,
                    stem="short_hook_9x16",
                )
            )
            words += captions.shift(hook_na.words, pause)
            t += hook_dur
        parts.append(_segment(ctx, scene.id, "9x16"))
        words += captions.shift(ctx.narration[scene.id].words, t + pause)
        t += ctx.durations[scene.id]
        end = _card(
            ctx, scene.id, "endcard", "Полное видео — на канале", ch.name, shorts.ENDCARD_SEC
        )
        parts.append(
            _segment(
                ctx,
                scene.id,
                "9x16",
                None,
                visual=end,
                duration=shorts.ENDCARD_SEC,
                stem="endcard_9x16",
            )
        )
        t += shorts.ENDCARD_SEC
        if t > shorts.MAX_SHORT_SEC:
            ctx.warnings.append(f"{sid}: {t:.0f} с > 60 с — шортс пропущен (озвучку не режем)")
            continue
        out_dir = ctx.vdir / "shorts" / sid
        spec_path = out_dir / "short.json"
        m, mpath = ctx.video_manifest()
        stage = f"short:{sid}"
        ihash = inputs_hash(*parts, [w.model_dump() for w in words], ch.style, ctx.encoder.name)
        if m.is_fresh(stage, SHORT_V, ihash, ctx.vdir) and spec_path.exists():
            _hit(ctx, stage)
            specs.append(ShortSpec.model_validate_json(spec_path.read_text(encoding="utf-8")))
            continue
        final = shorts.assemble_short(parts, words, out_dir, ch.style, ctx.encoder)
        info = probe.validate_video(final, width=1080, height=1920, need_audio=True)
        if info.duration > shorts.MAX_SHORT_SEC + 0.5:
            raise StageError(f"{sid}: итог {info.duration:.1f} с > 60 с", retryable=False)
        spec = ShortSpec(
            id=sid,
            scene_ids=[scene.id],
            hook=scene.short_hook,
            duration=round(info.duration, 3),
            video_key=svc.storage.key(final),
        )
        spec_path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
        m.record(stage, SHORT_V, ihash, ctx.vdir, [final, spec_path])
        m.save(mpath)
        ctx.ran.append(stage)
        specs.append(spec)
    return specs


# ---------------- metadata ----------------


def run_metadata(ctx: VideoCtx) -> VideoMeta:
    svc = ctx.svc
    m, mpath = ctx.video_manifest()
    prompt = load_prompt("metadata.md")
    ihash = inputs_hash(ctx.script, prompt, svc.llm.name)
    path = ctx.vdir / "meta.json"
    if m.is_fresh("metadata", META_V, ihash, ctx.vdir) and path.exists():
        _hit(ctx, "metadata")
        return VideoMeta.model_validate_json(path.read_text(encoding="utf-8"))
    payload = {
        "title": ctx.script.title,
        "hook": ctx.script.hook,
        "scenes": [{"type": s.type, "narration": s.narration[:300]} for s in ctx.script.scenes],
        "default_tags": svc.channel.default_tags,
    }
    text = svc.llm.complete(
        task="metadata",
        system=prompt,
        user="```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```",
    )
    data = extract_json(text)
    if not isinstance(data, dict):
        raise StageError("metadata: ожидался JSON-объект")
    tags = list(dict.fromkeys([*data.get("tags", []), *svc.channel.default_tags]))
    meta = VideoMeta(
        title=str(data.get("title") or ctx.script.title)[:100],
        description=str(data.get("description", "")),
        tags=tags,
        thumbnail_texts=[str(t) for t in data.get("thumbnail_texts", [])][:3],
    )
    path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    m.record("metadata", META_V, ihash, ctx.vdir, [path])
    m.save(mpath)
    ctx.ran.append("metadata")
    return meta


# ---------------- thumbnails + preview ----------------


def _frame_source(ctx: VideoCtx) -> Path | None:
    for scene in ctx.script.scenes:
        if scene.type in ("terminal", "code", "image", "diagram"):
            r = ctx.renders.get((scene.id, "16x9"))
            if r:
                return ctx.svc.storage.path(r.video_key)
    return None


def run_thumbnails(ctx: VideoCtx, meta: VideoMeta) -> list[ThumbnailVariant]:
    m, mpath = ctx.video_manifest()
    src = _frame_source(ctx)
    tdir = ctx.vdir / "thumbs"
    ihash = inputs_hash(meta.title, meta.thumbnail_texts, ctx.svc.channel.style, src or "no-frame")
    index = tdir / "thumbs.json"
    if m.is_fresh("thumbnails", THUMBS_V, ihash, ctx.vdir) and index.exists():
        _hit(ctx, "thumbnails")
        return [
            ThumbnailVariant.model_validate(x)
            for x in json.loads(index.read_text(encoding="utf-8"))
        ]
    tdir.mkdir(parents=True, exist_ok=True)
    frame = None
    if src is not None:
        frame = thumbs.grab_frame(src, tdir / "frame.png", probe.probe(src).duration * 0.6)
    variants = thumbs.render_all(
        meta.title, meta.thumbnail_texts, ctx.svc.channel.style, frame, tdir, ctx.svc.storage.key
    )
    index.write_text(
        json.dumps([v.model_dump() for v in variants], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    m.record(
        "thumbnails",
        THUMBS_V,
        ihash,
        ctx.vdir,
        [index, *(ctx.svc.storage.path(v.image_key) for v in variants)],
    )
    m.save(mpath)
    ctx.ran.append("thumbnails")
    return variants


def run_preview(ctx: VideoCtx, asm: VideoAssembly) -> Path:
    m, mpath = ctx.video_manifest()
    long_path = ctx.svc.storage.path(asm.long_key)
    out = ctx.vdir / "preview.mp4"
    ihash = inputs_hash(file_hash(long_path))
    if m.is_fresh("preview", PREVIEW_V, ihash, ctx.vdir):
        _hit(ctx, "preview")
        return out
    longform.preview(long_path, out)
    m.record("preview", PREVIEW_V, ihash, ctx.vdir, [out])
    m.save(mpath)
    ctx.ran.append("preview")
    return out
