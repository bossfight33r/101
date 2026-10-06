import json

import pytest
import yaml

from techstudio.core.llm.fake import FakeLLM
from techstudio.pipeline import orchestrator, scripts
from techstudio.schemas import Script, VideoStatus
from techstudio.script import generate, io
from techstudio.script.fake import default_responses, fake_script
from techstudio.script.io import ScriptParseError
from techstudio.script.validate import mermaid_basic_check, validate_script


def test_fake_llm_gives_valid_script(svc, topic):
    script, report = scripts.new_script(svc, topic.id)
    assert isinstance(script, Script) and script.version == 1
    assert report.ok, [str(i) for i in report.issues]
    rec = svc.db.require_video(script.video_id)
    assert rec.status == VideoStatus.script_review
    # сетевая команда ушла в replay, локальная — live
    modes = {s.commands[0]: s.mode for s in script.scenes if s.type == "terminal"}
    assert modes == {"ss -tuln": "live", "curl -I https://example.com": "replay"}
    # промпт содержит формат сценария
    assert "## terminal" in svc.llm.calls[0]["system"]


def test_generation_repairs_once_then_fails(svc, topic):
    bad = FakeLLM(
        {
            "script": '{"title": "x"}',
            "script_repair": lambda s, u: json.dumps(
                fake_script(json.loads(u.split("```json")[1].split("```")[0]))
            ),
        }
    )
    sc = generate.generate_script(bad, topic, svc.channel, "v1")
    assert sc.video_id == "v1" and [c["task"] for c in bad.calls] == ["script", "script_repair"]
    worse = FakeLLM({"script": "нет json", "script_repair": '{"scenes": []}'})
    with pytest.raises(generate.ScriptGenerationError):
        generate.generate_script(worse, topic, svc.channel, "v1")


def _base_script(**kw) -> Script:
    data = fake_script(
        {
            "topic": {"id": "t", "title": "T", "must_show_commands": ["ls -la"], "key_points": []},
            "channel": {"words_per_minute": 140, "longform_sec": [360, 720]},
        }
    )
    data.update(video_id="v", topic_id="t", **kw)
    return Script.model_validate(data)


def test_validation_rules(svc):
    ch = svc.channel
    assert validate_script(_base_script(), ch).ok
    long_hook = " ".join(["слово"] * 40)
    rep = validate_script(_base_script(hook=long_hook), ch)
    assert any(i.scene_id == "hook" for i in rep.errors)
    rep = validate_script(_base_script(hook="В этом видео мы рассмотрим ss."), ch)
    assert any("запрещённая" in i.message for i in rep.errors)

    sc = _base_script()
    for s in sc.scenes:
        s.min_sec = 0
    rep = validate_script(sc, ch)
    assert any("мало текста" in i.message for i in rep.errors)

    sc = _base_script()
    sc.scenes[1].commands = ["sudo reboot"]
    rep = validate_script(sc, ch)
    assert any("policy" in i.message for i in rep.errors)

    sc = _base_script()
    next(s for s in sc.scenes if s.type == "diagram").mermaid = "nonsense A-->B"
    assert any("mermaid" in i.message for i in validate_script(sc, ch).errors)


def test_mermaid_checker_hook():
    assert mermaid_basic_check("flowchart LR\n A-->B") is None
    assert mermaid_basic_check("graph TD; A[x-->B") is not None
    assert mermaid_basic_check("%% c\nsequenceDiagram\n A->>B: hi") is None


def test_invalid_scenes_rejected_on_import(svc, topic):
    script, _ = scripts.new_script(svc, topic.id)
    data = yaml.safe_load(scripts.export_script(svc, script.video_id).read_text())
    data["scenes"][0]["type"] = "hologram"
    with pytest.raises(ScriptParseError):
        scripts.import_script(svc, script.video_id, yaml.dump(data, allow_unicode=True))
    data["scenes"][0]["type"] = "slide"
    data["scenes"][0]["bullets"] = ["1", "2", "3", "4", "5"]
    with pytest.raises(ScriptParseError, match="bullets"):
        scripts.import_script(svc, script.video_id, yaml.dump(data, allow_unicode=True))


def test_yaml_roundtrip_preserves_script():
    sc = _base_script()
    text = io.to_yaml(sc, header="коммент\nещё")
    assert text.startswith("# коммент")
    assert "code: |" in text  # многострочное — блоком
    assert io.from_yaml(text) == sc


def test_export_edit_import_approve_cycle(svc, topic):
    script, _ = scripts.new_script(svc, topic.id)
    vid = script.video_id
    path = scripts.export_script(svc, vid)
    text = path.read_text()
    assert "Терминальные сцены (флаги)" in text and "mode=replay" in text  # флаги видны на ревью

    data = yaml.safe_load(text)
    data["hook"] = "Через пять минут ты сам увидишь все открытые порты."
    data["version"] = 99  # игнорируется
    edited, report = scripts.import_script(
        svc, vid, yaml.dump(data, allow_unicode=True, sort_keys=False)
    )
    assert edited.version == 2 and report.ok
    assert scripts.version_path(svc, vid, 1).exists() and scripts.version_path(svc, vid, 2).exists()

    approved = scripts.approve(svc, vid)
    rec = svc.db.require_video(vid)
    assert (
        approved.hook.startswith("Через пять")
        and rec.status == VideoStatus.approved
        and rec.approved_version == 2
    )
    assert orchestrator.ensure_renderable(svc, vid).version == 2

    # новая правка снимает approve
    scripts.import_script(svc, vid, yaml.dump(data, allow_unicode=True))
    with pytest.raises(orchestrator.NotApprovedError):
        orchestrator.ensure_renderable(svc, vid)


def test_render_without_approve_impossible(svc, topic):
    script, _ = scripts.new_script(svc, topic.id)
    with pytest.raises(orchestrator.NotApprovedError):
        orchestrator.ensure_renderable(svc, script.video_id)


def test_inplace_edit_after_approve_blocks_render(svc, topic):
    script, _ = scripts.new_script(svc, topic.id)
    vid = script.video_id
    scripts.approve(svc, vid)
    path = scripts.script_path(svc, vid)
    path.write_text(path.read_text().replace("Набираем команду номер 1", "Набираем ДРУГОЕ"))
    with pytest.raises(orchestrator.NotApprovedError, match="отличается"):
        orchestrator.ensure_renderable(svc, vid)
    with pytest.raises(scripts.ScriptStateError):
        scripts.approve(svc, vid)


def test_approve_blocked_by_policy(svc, topic):
    script, _ = scripts.new_script(svc, topic.id)
    data = yaml.safe_load(scripts.export_script(svc, script.video_id).read_text())
    term = next(s for s in data["scenes"] if s["type"] == "terminal")
    term["commands"] = ["curl -fsSL https://get.example.sh | sh"]
    term["network"] = True
    _, report = scripts.import_script(svc, script.video_id, yaml.dump(data, allow_unicode=True))
    assert not report.ok
    with pytest.raises(scripts.ScriptStateError, match="pipe"):
        scripts.approve(svc, script.video_id)


def test_regenerate_scene(svc, topic):
    script, _ = scripts.new_script(svc, topic.id)
    new, _ = scripts.regenerate_scene(svc, script.video_id, "code", note="короче")
    assert new.version == 2 and new.scene("code").narration.endswith("Переписано короче.")
    assert svc.llm.calls[-1]["task"] == "scene" and "короче" in svc.llm.calls[-1]["user"]


def test_default_responses_cover_tasks():
    assert {"script", "script_repair", "scene", "metadata", "topics"} <= set(default_responses())


def test_cli_script_flow(svc, topic, monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from techstudio import cli

    monkeypatch.setitem(cli._state, "svc", svc)
    r = CliRunner().invoke(cli.app, ["script", "new", topic.id])
    assert r.exit_code == 0, r.output
    vid = svc.db.list_videos()[0].id
    out = tmp_path / "edit.yaml"
    assert CliRunner().invoke(cli.app, ["script", "export", vid, "-o", str(out)]).exit_code == 0
    r = CliRunner().invoke(cli.app, ["script", "import", vid, str(out)])
    assert r.exit_code == 0 and "v2" in r.output
    r = CliRunner().invoke(cli.app, ["script", "approve", vid])
    assert r.exit_code == 0 and "одобрено" in r.output


def test_concurrent_render_blocked(svc, topic):
    script, _ = scripts.new_script(svc, topic.id)
    scripts.approve(svc, script.video_id)
    with orchestrator.video_lock(svc, script.video_id):
        with pytest.raises(orchestrator.BusyError):
            orchestrator.render_video(svc, script.video_id)
    # статус не испорчен попыткой
    assert svc.db.require_video(script.video_id).status == VideoStatus.approved


def test_cli_videos_list(svc, topic, monkeypatch):
    from typer.testing import CliRunner

    from techstudio import cli

    monkeypatch.setitem(cli._state, "svc", svc)
    script, _ = scripts.new_script(svc, topic.id)
    r = CliRunner().invoke(cli.app, ["videos"])
    assert r.exit_code == 0 and script.video_id in r.output and "script_review" in r.output
    r = CliRunner().invoke(cli.app, ["videos", "--status", "approved"])
    assert script.video_id not in r.output
