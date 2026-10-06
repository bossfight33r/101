import yaml

from techstudio.bot import logic
from techstudio.pipeline import scripts
from techstudio.schemas import VideoStatus

from .test_publish import ready  # noqa: F401 — фикстура


def test_admin_only(svc, monkeypatch):
    monkeypatch.setattr(type(svc.settings), "admin_id_set", property(lambda self: {42}))
    assert logic.is_admin(svc, 42) and not logic.is_admin(svc, 7) and not logic.is_admin(svc, None)


async def test_router_ignores_non_admin(svc, monkeypatch):
    from datetime import datetime

    from aiogram import Bot, Dispatcher
    from aiogram.dispatcher.event.bases import UNHANDLED
    from aiogram.types import Chat, Message, Update, User

    from techstudio.bot.handlers import build_router

    monkeypatch.setattr(type(svc.settings), "admin_id_set", property(lambda self: {42}))
    seen = []
    monkeypatch.setattr(logic, "handle_command", lambda *a: seen.append(a) or ([], None))
    dp = Dispatcher()
    dp.include_router(build_router(svc))
    bot = Bot("123456:TEST")

    def upd(uid):
        msg = Message(
            message_id=1,
            date=datetime.now(),
            chat=Chat(id=uid, type="private"),
            from_user=User(id=uid, is_bot=False, first_name="x"),
            text="/studio",
        )
        return Update(update_id=uid, message=msg)

    assert await dp.feed_update(bot, upd(7)) is UNHANDLED  # чужой — молчание
    assert seen == []
    await dp.feed_update(bot, upd(42))
    assert seen and seen[0][1] == "studio"
    await bot.session.close()


def test_script_gate_shows_flags_and_buttons(svc, topic):
    script, _ = scripts.new_script(svc, topic.id)
    (reply,) = logic.script_gate(svc, script.video_id)
    assert "REPLAY" in reply.text and "$ ss -tuln" in reply.text
    labels = [b[0] for row in reply.buttons for b in row]
    assert any("Approve" in x for x in labels) and any("правку" in x for x in labels)
    assert reply.documents[0].name == "script.yaml"
    assert all(len(d.encode()) <= 64 for row in reply.buttons for _, d in row)


def test_approve_button_triggers_render_job(svc, topic, monkeypatch):
    script, _ = scripts.new_script(svc, topic.id)
    called = {}
    monkeypatch.setattr(
        "techstudio.pipeline.orchestrator.render_video", lambda s, v: called.setdefault("vid", v)
    )
    monkeypatch.setattr(logic, "final_gate", lambda s, v: [logic.Reply(text="gate2")])
    replies, job = logic.handle_callback(svc, logic.cb("ok", script.video_id))
    assert (
        "одобрен" in replies[0].text
        and svc.db.require_video(script.video_id).status == VideoStatus.approved
    )
    assert job()[0].text == "gate2" and called["vid"] == script.video_id


def test_yaml_edit_via_document(svc, topic):
    script, _ = scripts.new_script(svc, topic.id)
    data = yaml.safe_load(scripts.export_script(svc, script.video_id).read_text())
    data["title"] = "Новый заголовок"
    replies = logic.handle_document(svc, "script.yaml", yaml.dump(data, allow_unicode=True))
    assert "v2" in replies[0].text and "Новый заголовок" in replies[1].text
    bad = logic.handle_document(svc, "script.yaml", "video_id: " + script.video_id + "\nscenes: 5")
    assert bad[0].text.startswith("⚠️")


def test_regenerate_scene_button(svc, topic):
    script, _ = scripts.new_script(svc, topic.id)
    (picker,), _ = logic.handle_callback(svc, logic.cb("rgm", script.video_id))
    first = picker.buttons[0][0][1]
    replies, _ = logic.handle_callback(svc, first)
    assert "переписана" in replies[0].text
    assert svc.db.require_video(script.video_id).script_version == 2


def test_final_gate_and_publish_flow(svc, ready):  # noqa: F811
    replies = logic.final_gate(svc, ready)
    assert replies[0].videos and replies[-1].text.count("Миниатюра: не выбрана") == 1
    assert "cmd2=REPLAY" in replies[-1].text
    labels = [b[0] for row in replies[-1].buttons for b in row]
    assert not any("публикация" in x for x in labels)  # без миниатюры approve недоступен
    gate, _ = logic.handle_callback(svc, logic.cb("th", ready, "C"))
    assert any("публикация" in b[0] for row in gate[-1].buttons for b in row)
    replies, job = logic.handle_callback(svc, logic.cb("fa", ready))
    assert job is not None
    out = job()
    assert "запланировано" in out[0].text and len(svc.publisher.uploads) == 3


def test_reject_button(svc, ready):  # noqa: F811
    logic.handle_callback(svc, logic.cb("fr", ready))
    assert svc.db.require_video(ready).status == VideoStatus.rejected


def test_commands(svc, topic):
    replies, job = logic.handle_command(svc, "new", [topic.id])
    gate = job()
    assert "Сценарий" in gate[0].text
    replies, _ = logic.handle_command(svc, "studio", [])
    assert "script_review" in replies[0].text


def test_edit_after_reject(svc, ready):  # noqa: F811
    logic.handle_callback(svc, logic.cb("fr", ready))
    data = yaml.safe_load(scripts.export_script(svc, ready).read_text())
    data["title"] = "Исправлено после reject"
    replies = logic.handle_document(svc, "script.yaml", yaml.dump(data, allow_unicode=True))
    assert "Правка принята" in replies[0].text
    assert svc.db.require_video(ready).status == VideoStatus.script_review


def _balanced_html(text: str) -> bool:
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.ok = [], True

        def handle_starttag(self, tag, attrs):
            if tag not in ("b", "code", "i"):
                self.ok = False
            self.stack.append(tag)

        def handle_endtag(self, tag):
            if not self.stack or self.stack.pop() != tag:
                self.ok = False

    p = P()
    p.feed(text)
    return p.ok and not p.stack


def test_gate_html_escapes_commands(svc, topic):
    script, _ = scripts.new_script(svc, topic.id)
    data = yaml.safe_load(scripts.export_script(svc, script.video_id).read_text())
    term = next(
        s for s in data["scenes"] if s["type"] == "terminal" and s.get("mode", "live") == "live"
    )
    term["commands"] = ["export API_KEY=<YOUR_KEY> && ss -tuln > ports.txt"]
    data["title"] = "a < b & c"
    logic.handle_document(svc, "script.yaml", yaml.dump(data, allow_unicode=True))
    (reply,) = logic.script_gate(svc, script.video_id)
    assert reply.html and "&lt;YOUR_KEY&gt;" in reply.text and "&amp;&amp;" in reply.text
    assert _balanced_html(reply.text)


def test_split_text_keeps_lines():
    from techstudio.bot.handlers import split_text

    text = "\n".join(f"<code>строка {i}</code>" for i in range(1000))
    chunks = split_text(text, limit=500)
    assert all(len(c) <= 500 for c in chunks) and "\n".join(chunks) == text
    assert all(_balanced_html(c) for c in chunks)
