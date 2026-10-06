import os
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from techstudio.core import ffmpeg, probe
from techstudio.core.encoder import X264_FAST
from techstudio.render.base import RenderEnv
from techstudio.render.code import CodeRenderer, tokenize, wrap_rows
from techstudio.render.diagram import DiagramRenderer, DockerMmdc, MermaidError
from techstudio.render.fake import FakeRenderer
from techstudio.render.image import ImageRenderer
from techstudio.render.slide import SlideRenderer
from techstudio.render.terminal import TapeError, TerminalRenderer, build_tape, quote_vhs
from techstudio.sandbox.docker import DockerSandbox, SandboxError
from techstudio.schemas import (
    ChannelStyle,
    CodeScene,
    DiagramScene,
    ImageScene,
    SlideScene,
    TerminalScene,
)

from .conftest import needs_ffmpeg

pytestmark = [needs_ffmpeg, pytest.mark.slow]
ASPECTS = [("16x9", 1920, 1080), ("9x16", 1080, 1920)]


@pytest.fixture
def env(svc):
    return RenderEnv(
        storage=svc.storage,
        video_dir=svc.video_dir("vtest"),
        style=ChannelStyle(),
        encoder=X264_FAST,
    )


def _valid(env, r, w, h, dur=None):
    path = env.storage.path(r.video_key)
    info = probe.validate_video(path, width=w, height=h, expected_duration=dur, tolerance=0.25)
    assert r.duration == pytest.approx(info.duration, abs=0.01)
    return info


@pytest.mark.parametrize("aspect,w,h", ASPECTS)
def test_slide_both_aspects(env, aspect, w, h):
    sc = SlideScene(
        id="s1",
        narration="n",
        title="Что сделаем сегодня",
        bullets=[
            "Зайдём по SSH",
            "Сменим пароль",
            "Поставим LuCI на русском языке, чтобы было удобно",
        ],
    )
    r = SlideRenderer(env).render(sc, aspect, 3.0)
    _valid(env, r, w, h, 3.0)
    assert r.aspect == aspect and not r.warnings


def test_slide_timeline_bullets_one_by_one():
    sr = SlideRenderer.__new__(SlideRenderer)
    sc = SlideScene(id="s", narration="n", title="T", bullets=["a", "b", "c"])
    durs = sr.timeline(sc, 6.0)
    assert len(durs) == 4 and sum(durs) == pytest.approx(6.0)


@pytest.mark.parametrize("aspect,w,h", ASPECTS)
def test_code_by_line_both_aspects(env, aspect, w, h):
    code = "import subprocess\n\ndef alive(host):\n    r = subprocess.run(['ping', '-c1', '-W1', host], capture_output=True, text=True, check=False)\n    return host, r.returncode == 0\n"
    sc = CodeScene(
        id="c1", narration="n", language="python", code=code, reveal="by_line", highlight_lines=[4]
    )
    r = CodeRenderer(env).render(sc, aspect, 4.0)
    _valid(env, r, w, h, 4.0)


def test_code_wraps_long_lines_in_vertical(env):
    lines, _, _ = tokenize("x = '" + "a" * 120 + "'\n", "python", "monokai")
    rows = wrap_rows(lines, 40)
    assert len(rows) >= 3 and rows[1].continuation
    lay_v = CodeRenderer(env).layout(
        CodeScene(id="c", narration="n", language="python", code="print(1)"), "9x16"
    )
    lay_h = CodeRenderer(env).layout(
        CodeScene(id="c", narration="n", language="python", code="print(1)"), "16x9"
    )
    # в 9:16 шрифт крупнее относительно ширины кадра (на телефоне)
    assert lay_v["font"].size / 1080 > lay_h["font"].size / 1920


def test_code_timeline_by_line():
    cr = CodeRenderer.__new__(CodeRenderer)
    sc = CodeScene(
        id="c",
        narration="n",
        language="python",
        code="a\nb\nc\nd",
        reveal="by_line",
        highlight_lines=[2],
    )
    tl = cr.timeline(sc, 6.0)
    assert [v for v, _, _ in tl][:3] == [1, 2, 3] and tl[-1][1] is True
    assert sum(d for *_, d in tl) == pytest.approx(6.0)


@pytest.mark.parametrize("aspect,w,h", ASPECTS)
def test_image_ken_burns(env, svc, aspect, w, h):
    Image.new("RGB", (1280, 800), (40, 120, 200)).save(svc.storage.ensure_dir("assets") / "x.png")
    sc = ImageScene(
        id="i1", narration="n", asset_key="assets/x.png", caption="LuCI после установки"
    )
    r = ImageRenderer(env).render(sc, aspect, 2.0)
    _valid(env, r, w, h, 2.0)
    assert not r.warnings


def test_image_missing_asset_falls_back(env):
    r = ImageRenderer(env).render(
        ImageScene(id="i2", narration="n", asset_key="assets/none.png"), "16x9", 2.0
    )
    _valid(env, r, 1920, 1080, 2.0)
    assert "нет ассета" in r.warnings[0]


class PilMermaid:
    name = "fake-mermaid"

    def render_png(self, source, out, width, height):
        out.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (width // 2, height // 2), (255, 255, 255, 200)).save(out)
        return out


class BrokenMermaid:
    name = "broken"

    def render_png(self, source, out, width, height):
        raise MermaidError("Parse error on line 2")


@pytest.mark.parametrize("aspect,w,h", ASPECTS)
def test_diagram_with_runner(env, aspect, w, h):
    sc = DiagramScene(id="d1", narration="n", mermaid="flowchart LR\n A-->B")
    r = DiagramRenderer(env, PilMermaid()).render(sc, aspect, 2.0)
    _valid(env, r, w, h, 2.0)
    assert not r.warnings


def test_diagram_error_gives_fallback_with_warning(env):
    sc = DiagramScene(id="d2", narration="n", mermaid="flowchart LR\n A-->B\n B-->C")
    r = DiagramRenderer(env, BrokenMermaid()).render(sc, "9x16", 2.0)
    _valid(env, r, 1080, 1920, 2.0)
    assert "fallback" in r.warnings[0]
    r = DiagramRenderer(env, None).render(sc, "16x9", 2.0)
    assert "fallback" in r.warnings[0]


def test_docker_mmdc_args_isolated(tmp_path):
    args = DockerMmdc("minlag/mermaid-cli:latest").build_args(tmp_path, 1920, 1080)
    assert args[args.index("--network") + 1] == "none" and "--user" in args


# ---------- terminal ----------


class FakeVhsRunner:
    """Имитирует `docker run ... vhs /out/scene.tape`: пишет /out/visual.mp4 нужного размера."""

    def __init__(self):
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[1] == "image":
            return subprocess.CompletedProcess(cmd, 0, "", "")
        mount = cmd[cmd.index("-v") + 1].split(":")[0]
        tape = (Path(mount) / "scene.tape").read_text()
        w = int(next(ln for ln in tape.splitlines() if ln.startswith("Set Width")).split()[-1])
        h = int(next(ln for ln in tape.splitlines() if ln.startswith("Set Height")).split()[-1])
        ffmpeg.run(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c=black:size={w}x{h}:rate=30:duration=2",
                *X264_FAST.args(),
                str(Path(mount) / "visual.mp4"),
            ]
        )
        return subprocess.CompletedProcess(cmd, 0, "", "")


def test_tape_generation_per_aspect():
    sc = TerminalScene(id="t", narration="n", commands=["ss -tuln", 'echo "hi"'], typing_speed=50)
    t16 = build_tape(sc, "16x9", 10.0, "Dracula")
    t9 = build_tape(sc, "9x16", 10.0, "Dracula")
    assert "Set Width 1920" in t16 and "Set Height 1080" in t16
    assert "Set Width 1080" in t9 and "Set Height 1920" in t9
    assert "Type 'echo \"hi\"'" in t16 and 'Type "ss -tuln"' in t16
    assert t16.count("Enter") == 3 and "Set TypingSpeed 50ms" in t16
    # хвостовой Sleep растёт с duration_hint
    assert build_tape(sc, "16x9", 20.0, "Dracula") != t16
    with pytest.raises(TapeError):
        quote_vhs("a\"b'c`d")


def test_terminal_live_runs_in_isolated_sandbox(env):
    runner = FakeVhsRunner()
    sb = DockerSandbox(runner=runner)
    sc = TerminalScene(id="t1", narration="n", commands=["ss -tuln"])
    r = TerminalRenderer(env, sb).render(sc, "16x9", 3.0)
    _valid(env, r, 1920, 1080)
    cmd = runner.calls[-1]
    assert cmd[cmd.index("--network") + 1] == "none"
    assert cmd[cmd.index("--user") + 1] == "1000:1000"
    assert "--read-only" in cmd and "ALL" in cmd and "no-new-privileges" in cmd
    mounts = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-v"]
    assert len(mounts) == 1 and mounts[0].endswith("vhs_16x9:/out:rw")


def test_terminal_network_flag_enables_network(env):
    runner = FakeVhsRunner()
    sc = TerminalScene(
        id="t2", narration="n", commands=["curl -I https://example.com"], network=True
    )
    r = TerminalRenderer(env, DockerSandbox(runner=runner)).render(sc, "9x16", 3.0)
    _valid(env, r, 1080, 1920)
    assert runner.calls[-1][runner.calls[-1].index("--network") + 1] == "bridge"
    assert any("network" in w for w in r.warnings)


def test_terminal_policy_blocks_before_docker(env):
    runner = FakeVhsRunner()
    sc = TerminalScene(id="t3", narration="n", commands=["rm -rf /"])
    with pytest.raises(SandboxError, match="policy"):
        TerminalRenderer(env, DockerSandbox(runner=runner)).render(sc, "16x9", 3.0)
    assert runner.calls == []


def test_terminal_replay_stages_real_output(env, svc):
    d = svc.storage.ensure_dir("assets/replay/ow/opkg")
    (d / "0.txt").write_text(
        "Downloading https://downloads.openwrt.org/...\nUpdated list of available packages\n"
    )
    runner = FakeVhsRunner()
    sc = TerminalScene(
        id="t4",
        narration="n",
        commands=["opkg update"],
        mode="replay",
        replay_output_key="assets/replay/ow/opkg",
    )
    r = TerminalRenderer(env, DockerSandbox(runner=runner)).render(sc, "16x9", 3.0)
    work = env.scene_dir("t4") / "vhs_16x9"
    assert (work / "replay" / "0.txt").read_text().startswith("Downloading")
    assert "extdebug" in (work / "replay_init.sh").read_text()
    assert "source /out/replay_init.sh" in (work / "scene.tape").read_text()
    assert runner.calls[-1][runner.calls[-1].index("--network") + 1] == "none"
    assert any("replay" in w for w in r.warnings)


def test_terminal_replay_missing_output(env):
    sc = TerminalScene(
        id="t5",
        narration="n",
        commands=["uci show"],
        mode="replay",
        replay_output_key="assets/replay/none",
    )
    with pytest.raises(SandboxError, match="replay"):
        TerminalRenderer(env, DockerSandbox(runner=FakeVhsRunner())).render(sc, "16x9", 3.0)


def test_sandbox_timeout_kills_container(tmp_path):
    calls = []

    def runner(cmd, **kw):
        calls.append(cmd)
        if cmd[1] == "run":
            raise subprocess.TimeoutExpired(cmd, 1)
        return subprocess.CompletedProcess(cmd, 0)

    with pytest.raises(SandboxError, match="лимит времени"):
        DockerSandbox(runner=runner).run(tmp_path, ["/out/scene.tape"])
    assert calls[-1][1] == "kill"


@pytest.mark.parametrize("aspect,w,h", ASPECTS)
def test_fake_renderer(env, aspect, w, h):
    r = FakeRenderer(env).render(SlideScene(id="f", narration="n", title="T"), aspect, 1.5)
    _valid(env, r, w, h, 1.5)


def test_fit_font_never_breaks_words():
    from techstudio.render import draw

    st = ChannelStyle()
    fnt, lines = draw.fit_font("ЗА 5 МИНУТ", st.font_bold, 550, 600, 150, 40)
    assert "МИНУТ" in lines


VHS = shutil.which(os.environ.get("TS_VHS_BIN", "vhs"))


@pytest.mark.skipif(VHS is None, reason="нет vhs (TS_VHS_BIN)")
@pytest.mark.parametrize("aspect", ["16x9", "9x16"])
@pytest.mark.parametrize(
    "scene",
    [
        TerminalScene(
            id="a",
            narration="n",
            commands=["ss -tuln", 'echo "hi there"', "grep -r 'listen' /etc | head"],
        ),
        TerminalScene(
            id="b",
            narration="n",
            commands=["opkg update"],
            mode="replay",
            replay_output_key="assets/k",
        ),
        TerminalScene(id="c", narration="n", commands=["printf '%s\\n' \"a b\""], typing_speed=30),
        TerminalScene(
            id="d", narration="n", commands=["curl -sI https://example.com | head -3"], network=True
        ),
    ],
)
def test_tape_passes_real_vhs_validate(tmp_path, scene, aspect):
    from techstudio.render.terminal import validate_tape

    tape = tmp_path / "scene.tape"
    tape.write_text(build_tape(scene, aspect, 9.0, "Dracula"))
    assert validate_tape(tape, VHS) is None


def test_orient_vertical_flowchart():
    from techstudio.render.diagram import orient

    assert orient("flowchart LR\n A-->B", "9x16").startswith("flowchart TD")
    assert orient("graph RL; A-->B", "9x16").startswith("graph BT")
    assert orient("flowchart LR\n A-->B", "16x9").startswith("flowchart LR")
    assert orient("sequenceDiagram\n A->>B: x", "9x16").startswith("sequenceDiagram")


def test_mermaid_error_summary_strips_stacktrace():
    from techstudio.render.diagram import error_summary

    out = "Generating\n\nError: Parse error on line 2:\nA--> -->B[\n---^\nExpecting 'X', got 'LINK'\nParser.parse (https://x/chunk.mjs:1:2)\n    at async Foo (file:///a.js:3:4)\n"
    s = error_summary(out)
    assert s.startswith("Error: Parse error") and "got 'LINK'" in s and ".mjs" not in s


MMDC = os.environ.get("TS_MERMAID_BIN")
MMDC_PPTR = os.environ.get("TS_MERMAID_PUPPETEER_CONFIG")


@pytest.mark.skipif(not MMDC, reason="реальный mmdc: TS_MERMAID_BIN (+TS_MERMAID_PUPPETEER_CONFIG)")
def test_real_mermaid_render_and_checker(env):
    from techstudio.render.diagram import LocalMmdc, make_checker

    runner = LocalMmdc(MMDC, puppeteer_config=MMDC_PPTR)
    sc = DiagramScene(
        id="dr",
        narration="n",
        mermaid="flowchart LR\n A[Ноутбук] --> B[Роутер]\n B --> C((Интернет))",
    )
    for aspect, w, h in ASPECTS:
        r = DiagramRenderer(env, runner).render(sc, aspect, 2.0)
        _valid(env, r, w, h, 2.0)
        assert not r.warnings
    check = make_checker(runner)
    assert check("graph TD; A-->B") is None
    assert "Parse error" in check("flowchart LR\n A--> -->B[")


def test_terminal_live_files_from_code_scene(env):
    from techstudio.schemas import Script

    script = Script(
        video_id="v",
        topic_id="t",
        title="T",
        hook="h",
        scenes=[
            {
                "type": "code",
                "id": "sweep",
                "narration": "n",
                "language": "python",
                "code": "print('up')\n",
            },
            {
                "type": "terminal",
                "id": "run",
                "narration": "n",
                "commands": ["python3 sweep.py"],
                "files": {"sweep.py": "sweep"},
            },
        ],
    )
    runner = FakeVhsRunner()
    term = script.scene("run")
    TerminalRenderer(env, DockerSandbox(runner=runner)).render(
        term, "16x9", 3.0, files=script.files_for(term)
    )
    work = env.scene_dir("run") / "vhs_16x9"
    assert (work / "files" / "sweep.py").read_text() == "print('up')\n"
    assert 'Type "cp -r /out/files/. ~/ && cd ~ && clear"' in (work / "scene.tape").read_text()
    with pytest.raises(SandboxError, match="нет содержимого"):
        TerminalRenderer(env, DockerSandbox(runner=runner)).render(term, "16x9", 3.0)


def test_files_must_reference_code_scene():
    from pydantic import ValidationError

    from techstudio.schemas import Script

    base = {"video_id": "v", "topic_id": "t", "title": "T", "hook": "h"}
    with pytest.raises(ValidationError, match="code-сцена"):
        Script(
            **base,
            scenes=[
                {
                    "type": "terminal",
                    "id": "a",
                    "narration": "n",
                    "commands": ["ls"],
                    "files": {"x.py": "nope"},
                }
            ],
        )
    with pytest.raises(ValidationError, match="без папок"):
        TerminalScene(id="a", narration="n", commands=["ls"], files={"../x.py": "c"})
    with pytest.raises(ValidationError, match="только для mode=live"):
        TerminalScene(
            id="a",
            narration="n",
            commands=["ls"],
            mode="replay",
            replay_output_key="assets/k",
            files={"x.py": "c"},
        )


def test_missing_font_falls_back_to_cyrillic_font():
    from techstudio.render import draw

    real = draw.resolve_font("/System/Library/Fonts/Supplemental/Arial Bold.ttf")
    assert "Bold" in real or "bold" in real.lower()
    f = draw.font("/nonexistent/SomeMono.ttf", 30)
    assert f.getmask("Ж").getbbox() is not None


def test_sandbox_read_only_toggle(tmp_path):
    from techstudio.sandbox.docker import SandboxLimits

    on = DockerSandbox().build_args(tmp_path, ["/out/scene.tape"], network=False, name="x")
    off = DockerSandbox(limits=SandboxLimits(read_only=False)).build_args(
        tmp_path, ["/out/scene.tape"], network=False, name="x"
    )
    assert "--read-only" in on and "--read-only" not in off
    assert off[off.index("--network") + 1] == "none" and "ALL" in off  # остальная изоляция на месте


def test_intermediate_frames_removed(env):
    sc = SlideScene(id="sf", narration="n", title="T", bullets=["a", "b"])
    SlideRenderer(env).render(sc, "16x9", 2.0)
    assert not (env.scene_dir("sf") / "frames_16x9").exists()
    assert env.visual_path("sf", "16x9").exists()


def test_sandbox_custom_network_for_network_scenes(tmp_path):
    sb = DockerSandbox(network_name="ts-internet-only")
    on = sb.build_args(tmp_path, ["/out/scene.tape"], network=True, name="x")
    off = sb.build_args(tmp_path, ["/out/scene.tape"], network=False, name="x")
    assert on[on.index("--network") + 1] == "ts-internet-only"
    assert off[off.index("--network") + 1] == "none"
