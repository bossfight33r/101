"""Контракты с реальными SDK без сети: тела запросов YouTube (статическая discovery + HttpMock),
параметры вызова Anthropic против сигнатуры SDK, отправка ответов бота."""

import inspect
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from googleapiclient.discovery import build
from googleapiclient.http import HttpMockSequence

from techstudio.publish.base import PublishError
from techstudio.publish.youtube import YouTubePublisher
from techstudio.schemas import Publication
from techstudio.track.collector import YouTubeCollector


class RecordingHttp(HttpMockSequence):
    def __init__(self, responses):
        super().__init__(responses)
        self.requests = []

    def request(self, uri, method="GET", body=None, headers=None, **kw):
        self.requests.append({"uri": uri, "method": method, "body": body, "headers": headers or {}})
        return super().request(uri, method, body, headers, **kw)


def yt_client(http):
    return build("youtube", "v3", http=http, static_discovery=True)


def test_youtube_upload_body_private_publish_at(tmp_path):
    video = tmp_path / "long.mp4"
    video.write_bytes(b"\x00" * 1024)
    http = RecordingHttp(
        [
            ({"status": "200", "location": "https://upload.example/session1"}, ""),
            ({"status": "200"}, json.dumps({"id": "yt123"})),
        ]
    )
    pub = YouTubePublisher(client=yt_client(http))
    at = datetime(2026, 10, 6, 15, 0, tzinfo=UTC)
    vid = pub.upload(
        video, title="T" * 120, description="D", tags=["linux"], language="ru", publish_at=at
    )
    assert vid == "yt123"
    first = http.requests[0]
    assert "uploadType=resumable" in first["uri"] and "part=snippet%2Cstatus" in first["uri"]
    body = json.loads(first["body"])
    assert body["status"] == {
        "privacyStatus": "private",
        "publishAt": "2026-10-06T15:00:00Z",
        "selfDeclaredMadeForKids": False,
    }
    assert len(body["snippet"]["title"]) == 100 and body["snippet"]["categoryId"] == "28"
    assert body["snippet"]["defaultAudioLanguage"] == "ru"


def test_youtube_captions_and_thumbnail_requests(tmp_path):
    srt = tmp_path / "c.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nПривет\n")
    jpg = tmp_path / "t.jpg"
    jpg.write_bytes(b"\xff\xd8\xff")
    http = RecordingHttp([({"status": "200"}, "{}"), ({"status": "200"}, "{}")])
    pub = YouTubePublisher(client=yt_client(http))
    pub.upload_captions("yt123", srt, "ru", "Русский")
    pub.set_thumbnail("yt123", jpg)
    cap, thumb = http.requests
    assert "/captions" in cap["uri"] and b"yt123" in (
        cap["body"] if isinstance(cap["body"], bytes) else cap["body"].encode()
    )
    assert "/thumbnails/set" in thumb["uri"] and "videoId=yt123" in thumb["uri"]


def test_youtube_http_error_classified(tmp_path):
    jpg = tmp_path / "t.jpg"
    jpg.write_bytes(b"\xff\xd8\xff")
    for status, retryable in (("403", False), ("503", True)):
        http = RecordingHttp([({"status": status}, json.dumps({"error": {"message": "x"}}))])
        with pytest.raises(PublishError) as e:
            YouTubePublisher(client=yt_client(http)).set_thumbnail("yt1", jpg)
        assert e.value.retryable is retryable


def test_collector_statistics_and_analytics():
    pubs = [
        Publication(
            id="v:long",
            video_id="v",
            kind="long",
            account_id="a",
            scheduled_at=datetime(2026, 10, 1, tzinfo=UTC),
            remote_id="yt1",
            status="published",
        )
    ]
    yt_http = RecordingHttp(
        [
            (
                {"status": "200"},
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "yt1",
                                "statistics": {
                                    "viewCount": "321",
                                    "likeCount": "9",
                                    "commentCount": "2",
                                },
                            }
                        ]
                    }
                ),
            )
        ]
    )
    ya_http = RecordingHttp([({"status": "200"}, json.dumps({"rows": [[95.5, 41.2, 1.25]]}))])
    col = YouTubeCollector(
        monetized=True,
        yt=yt_client(yt_http),
        ya=build("youtubeAnalytics", "v2", http=ya_http, static_discovery=True),
    )
    (snap,) = col.fetch(pubs)
    assert (snap.views, snap.likes, snap.comments) == (321, 9, 2)
    assert (snap.avg_view_duration, snap.avg_view_pct, snap.revenue) == (95.5, 41.2, 1.25)
    q = ya_http.requests[0]["uri"]
    assert (
        "filters=video%3D%3Dyt1" in q and "estimatedRevenue" in q and "ids=channel%3D%3DMINE" in q
    )


def test_collector_analytics_failure_does_not_break():
    pubs = [
        Publication(
            id="p",
            video_id="v",
            kind="short",
            account_id="a",
            scheduled_at=datetime(2026, 10, 1, tzinfo=UTC),
            remote_id="yt9",
            status="published",
        )
    ]
    yt_http = RecordingHttp(
        [
            (
                {"status": "200"},
                json.dumps({"items": [{"id": "yt9", "statistics": {"viewCount": "5"}}]}),
            )
        ]
    )
    ya_http = RecordingHttp([({"status": "403"}, json.dumps({"error": {"message": "no"}}))])
    col = YouTubeCollector(
        yt=yt_client(yt_http),
        ya=build("youtubeAnalytics", "v2", http=ya_http, static_discovery=True),
    )
    (snap,) = col.fetch(pubs)
    assert snap.views == 5 and snap.avg_view_pct is None


def test_anthropic_call_matches_sdk_signature(monkeypatch):
    """Параметры, которые мы передаём, существуют в сигнатуре beta.messages.stream установленного SDK."""
    from anthropic.resources.beta.messages import Messages

    from techstudio.core.llm import anthropic as backend

    captured = {}

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            class Block:
                type = "text"
                text = '{"ok": true}'

            class Usage:
                output_tokens = 5

            class Msg:
                stop_reason = "end_turn"
                content = [Block()]
                model = "claude-opus-5-5"
                usage = Usage()

            return Msg()

    llm = backend.AnthropicLLM(api_key="test-key-not-real")

    def stream(**kwargs):
        captured.update(kwargs)
        return FakeStream()

    monkeypatch.setattr(llm.client.beta.messages, "stream", stream)
    assert llm.complete(task="t", system="s", user="u") == '{"ok": true}'
    sig = inspect.signature(Messages.stream)
    sig.bind(None, **captured)  # TypeError, если параметр не существует
    assert captured["model"] == "claude-opus-5-5" and captured["thinking"] == {"type": "adaptive"}
    assert captured["fallbacks"] == "default" and captured["betas"] == [
        "server-side-fallback-2026-07-01"
    ]


def test_anthropic_refusal_and_max_tokens(monkeypatch):
    from techstudio.core.llm import anthropic as backend
    from techstudio.core.llm.base import LLMError

    def make(stop):
        class S:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get_final_message(self):
                return type(
                    "M", (), {"stop_reason": stop, "content": [], "model": "m", "usage": None}
                )()

        return lambda **kw: S()

    llm = backend.AnthropicLLM(api_key="test-key-not-real")
    for stop in ("refusal", "max_tokens"):
        monkeypatch.setattr(llm.client.beta.messages, "stream", make(stop))
        with pytest.raises(LLMError) as e:
            llm.complete(task="t", system="s", user="u")
        assert e.value.retryable is False


async def test_bot_send_replies_uses_right_methods(tmp_path):
    from techstudio.bot import handlers, logic

    vid, img, doc = tmp_path / "p.mp4", tmp_path / "a.jpg", tmp_path / "s.yaml"
    for p in (vid, img, doc):
        p.write_bytes(b"x")
    bot = AsyncMock()
    await handlers.send_replies(
        bot,
        1,
        [
            logic.Reply(videos=[vid], text="Превью"),
            logic.Reply(photos=[img, img, img]),
            logic.Reply(
                text="<b>Сценарий</b>", buttons=[[("✅", "ts:ok:v1")]], documents=[doc], html=True
            ),
            logic.Reply(text="❌ ошибка <без html>"),
        ],
    )
    assert (
        bot.send_video.await_count == 1 and bot.send_video.await_args.kwargs["caption"] == "Превью"
    )
    assert (
        bot.send_media_group.await_count == 1 and len(bot.send_media_group.await_args.args[1]) == 3
    )
    assert bot.send_document.await_count == 1
    gate, err = bot.send_message.await_args_list
    assert gate.kwargs["parse_mode"] == "HTML"
    assert gate.kwargs["reply_markup"].inline_keyboard[0][0].callback_data == "ts:ok:v1"
    assert err.kwargs["parse_mode"] is None


async def test_notify_sends_gate_to_each_admin(svc, topic, monkeypatch):
    from techstudio.bot import handlers
    from techstudio.pipeline import scripts

    monkeypatch.setattr(type(svc.settings), "admin_id_set", property(lambda self: {1, 2}))
    script, _ = scripts.new_script(svc, topic.id)
    bot = AsyncMock()
    assert await handlers.notify(svc, script.video_id, bot=bot) == 2
    chats = {c.args[0] for c in bot.send_message.await_args_list}
    assert chats == {1, 2} and bot.send_document.await_count == 2


async def test_run_job_updates_one_status_message():
    from types import SimpleNamespace

    from techstudio.bot import handlers, logic

    bot = AsyncMock()
    bot.send_message.return_value = SimpleNamespace(message_id=77)

    def job(progress=None):
        progress("🎙 Озвучка…")
        progress("🎞 Визуалы…")
        return [logic.Reply(text="готово")]

    await handlers.run_job(bot, 5, job)
    edits = [c.args[0] for c in bot.edit_message_text.await_args_list]
    assert edits[0] == "⏳ 🎙 Озвучка…"
    assert edits[1] == "✓ 🎙 Озвучка…\n⏳ 🎞 Визуалы…"
    assert edits[-1] == "✅ готово"
    assert all(c.kwargs["message_id"] == 77 for c in bot.edit_message_text.await_args_list)
    assert bot.send_message.await_args_list[-1].args[1] == "готово"
