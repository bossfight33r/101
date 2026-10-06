"""CLI `studio`."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from techstudio.core import log
from techstudio.schemas import AudienceLevel, Topic, TopicStatus
from techstudio.services import Services

app = typer.Typer(help="TechStudio: обучающие tech-видео без лица.", no_args_is_help=True)
topic_app = typer.Typer(help="Бэклог тем.", no_args_is_help=True)
app.add_typer(topic_app, name="topic")

_state: dict = {}


@app.callback()
def main(
    json_logs: bool = typer.Option(False, "--json-logs", help="Логи в JSON."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    log.configure(json=json_logs, verbose=verbose)


def services() -> Services:
    if "svc" not in _state:
        _state["svc"] = Services.from_settings()
    return _state["svc"]


def fail(msg: str, code: int = 1):
    typer.secho(msg, fg=typer.colors.RED, err=True)
    raise typer.Exit(code)


# ---------------- doctor ----------------


@app.command()
def doctor(as_json: bool = typer.Option(False, "--json")):
    """Проверить Docker, образ песочницы, VHS, Piper и голос, mermaid-cli, шрифты, ffmpeg."""
    from techstudio import doctor as d

    checks = d.run_all(services().settings)
    if as_json:
        typer.echo(json.dumps([c.__dict__ for c in checks], ensure_ascii=False, indent=2))
        return
    for c in checks:
        mark = "✅" if c.ok else ("❌" if c.required else "⚪")
        line = f"{mark} {c.name:28} {c.detail}"
        if not c.ok and c.hint:
            line += f"  → {c.hint}"
        typer.echo(line)
    missing = [c.name for c in checks if c.required and not c.ok]
    typer.echo(f"\nНе хватает обязательных: {len(missing)}" if missing else "\nВсё на месте.")


# ---------------- topics ----------------


@topic_app.command("add")
def topic_add(
    topic_id: str,
    title: str = typer.Option(..., "--title", "-t"),
    level: AudienceLevel = typer.Option(AudienceLevel.beginner, "--level"),
    point: list[str] = typer.Option([], "--point", "-p", help="Ключевой пункт (можно много)."),
    command: list[str] = typer.Option([], "--command", "-c", help="Обязательная команда."),
    notes: str = typer.Option("", "--notes"),
    overwrite: bool = typer.Option(False, "--overwrite"),
):
    from techstudio.topics import backlog

    t = Topic(
        id=topic_id,
        title=title,
        audience_level=level,
        key_points=point,
        must_show_commands=command,
        notes=notes,
    )
    try:
        backlog.add(services().db, t, overwrite=overwrite)
    except ValueError as e:
        fail(str(e))
    typer.echo(f"добавлено: {t.id}")


@topic_app.command("list")
def topic_list(status: TopicStatus | None = typer.Option(None, "--status")):
    from techstudio.topics import backlog

    for t in backlog.list_topics(services().db, status):
        typer.echo(f"{t.id:32} {t.status.value:12} {t.audience_level.value:12} {t.title}")


@topic_app.command("import")
def topic_import(path: Path, overwrite: bool = typer.Option(False, "--overwrite")):
    from techstudio.topics import backlog

    added, skipped = backlog.import_file(services().db, path, overwrite=overwrite)
    typer.echo(f"импортировано: {added}, пропущено (уже есть): {skipped}")


# ---------------- script ----------------

script_app = typer.Typer(help="Сценарий: генерация, ревью, правка, approve.", no_args_is_help=True)
app.add_typer(script_app, name="script")


def _print_report(report) -> None:
    typer.echo(f"оценка длительности: {report.estimated_sec / 60:.1f} мин")
    for issue in report.issues:
        color = typer.colors.RED if issue.level == "error" else typer.colors.YELLOW
        typer.secho(f"  {issue}", fg=color)
    typer.secho(
        "валидация: ок" if report.ok else "валидация: есть ошибки — approve недоступен",
        fg=typer.colors.GREEN if report.ok else typer.colors.RED,
    )


@script_app.command("new")
def script_new(topic_id: str):
    """Сгенерировать сценарий по теме → статус script_review."""
    from techstudio.pipeline import scripts

    try:
        script, report = scripts.new_script(services(), topic_id)
    except Exception as e:  # noqa: BLE001 — показать Боссу кратко
        fail(f"не удалось: {e}")
    typer.echo(f"видео: {script.video_id}  v{script.version}  сцен: {len(script.scenes)}")
    _print_report(report)
    typer.echo(f"сценарий: {scripts.script_path(services(), script.video_id)}")


@script_app.command("export")
def script_export(video_id: str, out: Path | None = typer.Option(None, "--out", "-o")):
    """Выгрузить script.yaml для правки."""
    from techstudio.pipeline import scripts

    try:
        typer.echo(str(scripts.export_script(services(), video_id, out)))
    except Exception as e:  # noqa: BLE001
        fail(str(e))


@script_app.command("import")
def script_import(video_id: str, path: Path):
    """Загрузить правку: валидация → version+1 → script_review."""
    from techstudio.pipeline import scripts

    try:
        script, report = scripts.import_script(
            services(), video_id, path.read_text(encoding="utf-8")
        )
    except Exception as e:  # noqa: BLE001
        fail(str(e))
    typer.echo(f"импортировано: v{script.version}")
    _print_report(report)


@script_app.command("approve")
def script_approve(video_id: str):
    """Одобрить текущую версию сценария (без этого рендер невозможен)."""
    from techstudio.pipeline import scripts

    try:
        script = scripts.approve(services(), video_id)
    except Exception as e:  # noqa: BLE001
        fail(str(e))
    typer.secho(f"одобрено: {video_id} v{script.version}", fg=typer.colors.GREEN)


@script_app.command("regen")
def script_regen(video_id: str, scene_id: str, note: str = typer.Option("", "--note")):
    """Перегенерировать одну сцену."""
    from techstudio.pipeline import scripts

    try:
        script, report = scripts.regenerate_scene(services(), video_id, scene_id, note)
    except Exception as e:  # noqa: BLE001
        fail(str(e))
    typer.echo(f"сцена {scene_id} переписана: v{script.version}")
    _print_report(report)


# ---------------- render / status / retry ----------------


def _print_summary(summary: dict) -> None:
    long = summary["long"]
    typer.echo(
        f"длинное: {long['long_key']}  {long['duration'] / 60:.1f} мин  глав: {len(long['chapters'])}"
    )
    for s in summary["shorts"]:
        typer.echo(f"шортс {s['id']}: {s['duration']:.0f} с  {s['video_key']}")
    typer.echo("миниатюры: " + ", ".join(f"{t['id']}={t['text']}" for t in summary["thumbnails"]))
    for w in summary["warnings"]:
        typer.secho(f"  ⚠ {w}", fg=typer.colors.YELLOW)
    typer.echo(f"этапов выполнено: {len(summary['ran'])}, из кеша: {len(summary['cache_hits'])}")


@app.command()
def render(
    video_id: str, scene: str | None = typer.Option(None, "--scene", help="Перерендер одной сцены.")
):
    """Озвучка → визуалы → сборка (только после approve сценария)."""
    from techstudio.pipeline import orchestrator

    try:
        summary = (
            orchestrator.rerender_scene(services(), video_id, scene)
            if scene
            else orchestrator.render_video(services(), video_id)
        )
    except orchestrator.NotApprovedError as e:
        fail(f"рендер запрещён: {e}")
    except Exception as e:  # noqa: BLE001
        fail(f"рендер упал: {type(e).__name__}: {e}\nпосле исправления: studio retry {video_id}")
    typer.secho("готово → final_review", fg=typer.colors.GREEN)
    _print_summary(summary)


@app.command()
def status(video_id: str, as_json: bool = typer.Option(False, "--json")):
    """Статус видео, ошибка этапа, история переходов."""
    svc = services()
    rec = svc.db.get_video(video_id)
    if rec is None:
        fail(f"видео {video_id} не найдено")
    events = svc.db.video_events(video_id)
    if as_json:
        typer.echo(
            json.dumps(
                {"video": rec.model_dump(mode="json"), "events": events},
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    typer.echo(
        f"{rec.id}: {rec.status.value}  сценарий v{rec.script_version}  одобрен v{rec.approved_version}"
    )
    if rec.failure:
        f = rec.failure
        typer.secho(
            f"ошибка на этапе {f.stage}: {f.error_type}: {f.message} (retryable={f.retryable})",
            fg=typer.colors.RED,
        )
    for e in events:
        typer.echo(f"  {e['ts'][:19]}  {e['from_status'] or '-'} → {e['to_status']}")


@app.command("retry")
def retry_cmd(video_id: str):
    """Повторить упавший рендер: готовые этапы берутся из кеша."""
    from techstudio.pipeline import orchestrator

    try:
        summary = orchestrator.retry(services(), video_id)
    except Exception as e:  # noqa: BLE001
        fail(f"retry не удался: {type(e).__name__}: {e}")
    typer.secho("готово → final_review", fg=typer.colors.GREEN)
    _print_summary(summary)


# ---------------- review / publish / auth / bot ----------------


@app.command("review")
def review_cmd(
    video_id: str,
    action: str = typer.Argument(..., help="approve | reject | thumb"),
    thumb: str | None = typer.Option(None, "--thumb", help="A/B/C"),
    reason: str = typer.Option("", "--reason"),
):
    """Финальное ревью: выбрать миниатюру, одобрить или отклонить."""
    from techstudio.pipeline import review

    svc = services()
    try:
        if action == "approve":
            review.approve(svc, video_id, thumb)
            typer.secho(
                f"одобрено: {video_id} (миниатюра {svc.db.require_video(video_id).thumbnail_id})",
                fg=typer.colors.GREEN,
            )
        elif action == "reject":
            review.reject(svc, video_id, reason)
            typer.echo(f"отклонено: {video_id}")
        elif action == "thumb" and thumb:
            review.choose_thumbnail(svc, video_id, thumb)
            typer.echo(f"миниатюра: {thumb}")
        else:
            fail("действие: approve | reject | thumb --thumb X")
    except review.ReviewError as e:
        fail(str(e))


@app.command("publish")
def publish_cmd(video_id: str):
    """Загрузить на YouTube и запланировать (только после финального approve)."""
    from techstudio.pipeline import publish

    try:
        pubs = publish.publish_video(services(), video_id)
    except Exception as e:  # noqa: BLE001
        fail(f"публикация: {type(e).__name__}: {e}")
    for p in pubs:
        typer.echo(
            f"{p.kind:5} {p.short_id or '':16} {p.scheduled_at:%Y-%m-%d %H:%M} UTC  {p.status}  {p.url or ''}"
        )
        for n in p.notes:
            typer.secho(f"  ⚠ {n}", fg=typer.colors.YELLOW)


auth_app = typer.Typer(help="OAuth.", no_args_is_help=True)
app.add_typer(auth_app, name="auth")


@auth_app.command("youtube")
def auth_youtube(account: str | None = typer.Option(None, "--account")):
    """Авторизация YouTube в браузере, токен → data/studio/secrets/<account>.json."""
    from techstudio.publish.youtube import authorize, token_path

    svc = services()
    secrets = svc.settings.resolve(svc.settings.youtube_client_secrets)
    if not secrets.exists():
        fail(f"нет {secrets} — см. docs/studio/runbook.md#youtube")
    token = authorize(
        secrets, token_path(svc.storage.path("secrets"), account or svc.channel.account_id)
    )
    typer.echo(f"токен сохранён: {token}")


@app.command()
def bot():
    """Запустить Telegram-бота (раздел TechStudio, только TS_ADMIN_IDS)."""
    import asyncio

    from techstudio.bot.handlers import run_polling

    try:
        asyncio.run(run_polling(services()))
    except RuntimeError as e:
        fail(str(e))
