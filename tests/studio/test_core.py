import json

import pytest
from typer.testing import CliRunner

from techstudio.core.manifest import Manifest, inputs_hash
from techstudio.core.storage import LocalStorage
from techstudio.schemas import FailureInfo, Topic, VideoStatus
from techstudio.voice.base import apply_pronunciation


def test_storage_rejects_escape(tmp_path):
    st = LocalStorage(tmp_path)
    with pytest.raises(ValueError):
        st.path("../etc/passwd")
    p = st.write_text("a/b.txt", "x")
    assert st.key(p) == "a/b.txt"


def test_manifest_fresh_by_hash(tmp_path):
    out = tmp_path / "o.txt"
    out.write_text("1")
    m = Manifest()
    h = inputs_hash({"a": 1})
    m.record("st", 1, h, tmp_path, [out])
    m.save(tmp_path / "manifest.json")
    m2 = Manifest.load(tmp_path / "manifest.json")
    assert m2.is_fresh("st", 1, h, tmp_path)
    assert not m2.is_fresh("st", 2, h, tmp_path)  # stage_version
    assert not m2.is_fresh("st", 1, inputs_hash({"a": 2}), tmp_path)  # входы
    out.write_text("2")  # выход изменён
    assert not m2.is_fresh("st", 1, h, tmp_path)


def test_db_video_lifecycle(svc):
    db = svc.db
    db.upsert_topic(Topic(id="t1", title="T"))
    db.create_video("v1", "t1", "ch")
    db.update_video("v1", status=VideoStatus.script_review, script_version=1)
    rec = db.update_video(
        "v1",
        status=VideoStatus.failed,
        failure=FailureInfo(stage="voice", error_type="X", message="m"),
    )
    assert rec.failure.stage == "voice"
    events = [e["to_status"] for e in db.video_events("v1")]
    assert events == ["draft", "script_review", "failed"]


def test_pronunciation_only_whole_terms():
    m = {"SSH": "эс-эс-аш", "OpenWrt": "Оупэн"}
    assert apply_pronunciation("Заходим по SSH на OpenWrt.", m) == "Заходим по эс-эс-аш на Оупэн."
    assert apply_pronunciation("SSHD", m) == "SSHD"


def test_cli_help_and_doctor(svc, monkeypatch):
    from techstudio import cli

    monkeypatch.setitem(cli._state, "svc", svc)
    r = CliRunner().invoke(cli.app, ["--help"])
    assert r.exit_code == 0 and "doctor" in r.output
    r = CliRunner().invoke(cli.app, ["doctor", "--json"])
    assert r.exit_code == 0
    names = {c["name"] for c in json.loads(r.output)}
    assert {"ffmpeg", "sandbox image", "mermaid-cli", "piper"} <= names


def test_cli_topic_import_list(svc, monkeypatch):
    from techstudio import cli
    from techstudio.config import ROOT

    monkeypatch.setitem(cli._state, "svc", svc)
    r = CliRunner().invoke(
        cli.app, ["topic", "import", str(ROOT / "config/studio/topics.example.yaml")]
    )
    assert r.exit_code == 0, r.output
    r = CliRunner().invoke(cli.app, ["topic", "list"])
    assert "openwrt-first-steps" in r.output


def test_doctor_strict_exit_code(svc, monkeypatch):
    from techstudio import cli, doctor

    monkeypatch.setitem(cli._state, "svc", svc)
    monkeypatch.setattr(doctor, "run_all", lambda s: [doctor.Check("x", False, "нет")])
    assert CliRunner().invoke(cli.app, ["doctor"]).exit_code == 0
    assert CliRunner().invoke(cli.app, ["doctor", "--strict"]).exit_code == 1


def test_bad_channel_config_is_readable(tmp_path, monkeypatch):
    from techstudio import cli

    bad = tmp_path / "channel.yaml"
    bad.write_text("id: x\nname: y\nvoice_id: v\naccount_id: a\nwords_per_minute: 5\n")
    monkeypatch.setenv("TS_CHANNEL_FILE", str(bad))
    monkeypatch.setenv("TS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    cli._state.pop("svc", None)
    r = CliRunner().invoke(cli.app, ["topic", "list"])
    cli._state.pop("svc", None)
    assert r.exit_code == 1
    assert "words_per_minute" in r.output and "Traceback" not in r.output


def test_db_backup_cli_and_rotation(svc, monkeypatch):
    import sqlite3

    from techstudio import cli

    svc.db.upsert_topic(Topic(id="t1", title="T"))
    monkeypatch.setitem(cli._state, "svc", svc)
    for _ in range(3):
        r = CliRunner().invoke(cli.app, ["backup", "--keep", "2"])
        assert r.exit_code == 0, r.output
        import time

        time.sleep(1.05)
    files = sorted(svc.storage.path("backups").glob("studio-*.db"))
    assert len(files) == 2
    rows = sqlite3.connect(files[-1]).execute("SELECT id FROM topics").fetchall()
    assert rows == [("t1",)]
