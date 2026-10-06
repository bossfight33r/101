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
