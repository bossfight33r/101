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
