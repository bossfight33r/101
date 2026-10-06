import pytest
from pydantic import TypeAdapter, ValidationError

from techstudio.schemas import (
    Channel,
    CodeScene,
    ImageScene,
    Scene,
    Script,
    SlideScene,
    TerminalScene,
    Topic,
)

SCENE = TypeAdapter(Scene)


def test_scene_discriminator_picks_type():
    s = SCENE.validate_python(
        {"type": "terminal", "id": "s1", "narration": "x", "commands": ["ls"]}
    )
    assert isinstance(s, TerminalScene) and s.network is False and s.mode == "live"
    s = SCENE.validate_python({"type": "slide", "id": "s2", "narration": "x", "title": "T"})
    assert isinstance(s, SlideScene)


def test_unknown_scene_type_rejected():
    with pytest.raises(ValidationError):
        SCENE.validate_python({"type": "video", "id": "s1", "narration": "x"})


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        SCENE.validate_python(
            {"type": "slide", "id": "s1", "narration": "x", "title": "T", "foo": 1}
        )


def test_slide_max_four_bullets():
    with pytest.raises(ValidationError):
        SlideScene(id="s", narration="x", title="T", bullets=["1", "2", "3", "4", "5"])


def test_replay_requires_output_key():
    with pytest.raises(ValidationError):
        TerminalScene(id="s", narration="x", commands=["uci show"], mode="replay")
    ok = TerminalScene(
        id="s",
        narration="x",
        commands=["uci show"],
        mode="replay",
        replay_output_key="assets/r/x.txt",
    )
    assert ok.mode == "replay"


def test_code_highlight_in_range():
    with pytest.raises(ValidationError):
        CodeScene(id="c", narration="x", language="python", code="a=1\nb=2", highlight_lines=[3])


def test_script_unique_scene_ids_and_reserved():
    base = {"type": "slide", "narration": "x", "title": "T"}
    with pytest.raises(ValidationError):
        Script(
            video_id="v",
            topic_id="t",
            title="T",
            hook="h",
            scenes=[{**base, "id": "a"}, {**base, "id": "a"}],
        )
    with pytest.raises(ValidationError):
        Script(video_id="v", topic_id="t", title="T", hook="h", scenes=[{**base, "id": "hook"}])


def test_script_roundtrip_json():
    sc = Script(
        video_id="v",
        topic_id="t",
        title="T",
        hook="h",
        scenes=[
            {"type": "terminal", "id": "a", "narration": "n", "commands": ["ls -la"]},
            {"type": "code", "id": "b", "narration": "n", "language": "python", "code": "print(1)"},
            {"type": "diagram", "id": "c", "narration": "n", "mermaid": "graph LR; A-->B"},
            {"type": "image", "id": "d", "narration": "n", "asset_key": "assets/x.png"},
        ],
    )
    assert Script.model_validate_json(sc.model_dump_json()) == sc


def test_topic_id_pattern():
    with pytest.raises(ValidationError):
        Topic(id="Bad Id", title="x")


def test_channel_example_loads():
    from techstudio.config import ROOT, load_channel, load_topics, load_voices

    ch = load_channel(ROOT / "config/studio/channel.example.yaml")
    assert isinstance(ch, Channel) and ch.daily_limits.long == 1 and ch.daily_limits.shorts == 3
    assert len(load_topics(ROOT / "config/studio/topics.example.yaml")) >= 3
    v = load_voices(ROOT / "config/studio/voices.yaml")
    assert ch.voice_id in v.voices and "OpenWrt" in v.pronunciation


@pytest.mark.parametrize(
    "key",
    [
        "../.env",
        "/etc/passwd",
        "assets/../secrets/yt.json",
        "secrets/yt_main.json",
        "assets//x",
        "assets/x/../../y",
    ],
)
def test_asset_keys_cannot_escape(key):
    with pytest.raises(ValidationError):
        ImageScene(id="i", narration="n", asset_key=key)
    with pytest.raises(ValidationError):
        TerminalScene(
            id="t", narration="n", commands=["uci show"], mode="replay", replay_output_key=key
        )


def test_asset_keys_ok():
    assert ImageScene(
        id="i", narration="n", asset_key="assets/openwrt/luci-ru.png"
    ).asset_key.endswith(".png")
    TerminalScene(
        id="t",
        narration="n",
        commands=["opkg update"],
        mode="replay",
        replay_output_key="assets/replay/ow/opkg-update",
    )
