import hashlib
from datetime import timedelta

import pytest

from techstudio.pipeline import publish, review
from techstudio.prompts import load as load_prompt
from techstudio.schemas import TopicStatus, VideoStatus
from techstudio.topics import suggest
from techstudio.track import report as rep_mod
from techstudio.track.collector import FakeCollector, collect

from .test_publish import NOW, ready  # noqa: F401


def _published(svc, vid):
    review.approve(svc, vid, "A")
    pubs = publish.publish_video(svc, vid, NOW)
    svc.overrides["collector"] = FakeCollector(
        {
            f"{vid}:long": {"views": 1000, "avg_view_pct": 55.0, "revenue": 1.5},
            f"{vid}:short-cmd1": {"views": 5000, "avg_view_pct": 80.0},
            f"{vid}:short-code": {"views": 700, "avg_view_pct": 40.0},
        }
    )
    return pubs


def test_track_collects_only_published(svc, ready):  # noqa: F811
    pubs = _published(svc, ready)
    assert collect(svc, NOW) == 0  # ещё ничего не вышло
    n = collect(svc, max(p.scheduled_at for p in pubs) + timedelta(minutes=1))
    assert n == 3 and svc.db.count_snapshots() == 3
    collect(svc, max(p.scheduled_at for p in pubs) + timedelta(minutes=2))
    assert svc.db.count_snapshots() == 6  # append-only


def test_report_topics_scene_types_hooks(svc, ready):  # noqa: F811
    pubs = _published(svc, ready)
    collect(svc, max(p.scheduled_at for p in pubs) + timedelta(minutes=1))
    rep = rep_mod.build_report(svc)
    assert rep.topics[0]["key"] == "ss: кто слушает порты" and rep.topics[0]["avg_view_pct"] == 55.0
    assert rep.scene_types_shorts[0]["key"] == "terminal"  # cmd1 удержал лучше code
    assert {r["key"] for r in rep.scene_types_long} >= {"terminal", "code", "slide"}
    assert rep.hooks_shorts[0]["views"] == 5000
    assert rep.totals["revenue"] == 1.5
    text = rep_mod.to_text(rep)
    assert "Типы сцен в шортсах" in text and "terminal" in text


def test_recommendations_do_not_touch_prompts(svc, ready, monkeypatch):  # noqa: F811
    from typer.testing import CliRunner

    from techstudio import cli

    pubs = _published(svc, ready)
    collect(svc, max(p.scheduled_at for p in pubs) + timedelta(minutes=1))
    before = hashlib.sha256(load_prompt("script.md").encode()).hexdigest()
    monkeypatch.setitem(cli._state, "svc", svc)
    r = CliRunner().invoke(cli.app, ["report", "--recommendations"])
    assert r.exit_code == 0, r.output
    files = list(svc.storage.path("reports").glob("recommendations-*.md"))
    assert files and "применять вручную" in files[0].read_text()
    assert hashlib.sha256(load_prompt("script.md").encode()).hexdigest() == before


def test_empty_report(svc):
    rep = rep_mod.build_report(svc)
    assert rep.topics == [] and "мало данных" in rep_mod.recommendations(rep)


def test_topic_suggestions_need_manual_accept(svc, topic):
    path = suggest.suggest(svc, rep_mod.build_report(svc).as_dict())
    assert path.exists() and "wireguard-openwrt" in path.read_text()
    assert svc.db.get_topic("wireguard-openwrt") is None  # не в бэклоге без одобрения
    assert suggest.accept(svc, path, ["wireguard-openwrt"]) == ["wireguard-openwrt"]
    assert svc.db.get_topic("wireguard-openwrt").status == TopicStatus.backlog
    assert suggest.accept(svc, path, [], accept_all=True) == []  # повтор не дублирует


def test_report_uses_published_version_and_views_per_day(svc, ready):  # noqa: F811
    import yaml

    from techstudio.pipeline import scripts

    pubs = _published(svc, ready)
    # после публикации Босс правит сценарий — отчёт должен смотреть на опубликованную версию
    data = yaml.safe_load(scripts.export_script(svc, ready).read_text())
    data["hook"] = "Новый хук после публикации."
    svc.db.update_video(ready, status=VideoStatus.final_review)
    rec = svc.db.require_video(ready)
    svc.db.update_video(ready, approved_version=rec.script_version)
    published_hook = scripts.load_script(svc, ready).hook
    scripts.import_script(svc, ready, yaml.dump(data, allow_unicode=True))
    svc.db.update_video(ready, approved_version=1)
    collect(svc, max(p.scheduled_at for p in pubs) + timedelta(days=10))
    rep = rep_mod.build_report(svc)
    assert rep.hooks_long[0]["hook"] == published_hook
    assert rep.topics[0]["views_per_day"] == pytest.approx(
        100.0, rel=0.15
    )  # 1000 просмотров / ~10 дней
