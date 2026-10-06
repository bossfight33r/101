"""Код: Pygments-подсветка → кадры Pillow. by_line — построчное появление, highlight_lines — фон.
В 9:16 шрифт крупнее и длинные строки переносятся."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import ImageDraw
from pygments import lex
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.styles import get_style_by_name
from pygments.token import Token
from pygments.util import ClassNotFound

from techstudio.render import draw
from techstudio.render.base import RenderEnv, finish, frames_to_video, size_of
from techstudio.schemas import Aspect, CodeScene, SceneRender

LINE_STEP = 1.0  # сек на строку при by_line (максимум)


@dataclass
class Row:
    line_no: int  # номер исходной строки (1-based)
    tokens: list[tuple[str, tuple[int, int, int], bool]]
    continuation: bool = False


def tokenize(
    code: str, language: str, theme: str
) -> tuple[list[list[tuple[str, tuple, bool]]], tuple, tuple]:
    try:
        lexer = get_lexer_by_name(language)
    except ClassNotFound:
        lexer = TextLexer()
    try:
        style = get_style_by_name(theme)
    except ClassNotFound:
        style = get_style_by_name("monokai")
    bg = draw.rgb(style.background_color or "#272822")
    base = style.style_for_token(Token.Text)["color"]
    default_fg = draw.rgb(base) if base else (248, 248, 242)
    lines: list[list[tuple[str, tuple, bool]]] = [[]]
    for ttype, value in lex(code.rstrip("\n") + "\n", lexer):
        st = style.style_for_token(ttype)
        color = draw.rgb(st["color"]) if st["color"] else default_fg
        parts = value.split("\n")
        for i, part in enumerate(parts):
            if i > 0:
                lines.append([])
            if part:
                lines[-1].append((part.replace("\t", "    "), color, bool(st["bold"])))
    if lines and not lines[-1]:
        lines.pop()
    return lines, bg, default_fg


def wrap_rows(lines, max_cols: int) -> list[Row]:
    rows: list[Row] = []
    for no, tokens in enumerate(lines, 1):
        cur: list = []
        col = 0
        first = True
        for text, color, bold in tokens:
            while text:
                room = max_cols - col
                if room <= 0:
                    rows.append(Row(no, cur, not first))
                    first, cur, col = False, [], 2  # отступ продолжения
                    cur.append(("↪ ", (120, 120, 120), False))
                    room = max_cols - col
                piece, text = text[:room], text[room:]
                cur.append((piece, color, bold))
                col += len(piece)
        rows.append(Row(no, cur, not first))
    return rows


class CodeRenderer:
    name = "code"
    version = 1

    def __init__(self, env: RenderEnv):
        self.env = env

    def _line_count(self, scene: CodeScene) -> int:
        return len(scene.code.rstrip("\n").splitlines())

    def min_duration(self, scene: CodeScene) -> float:
        if scene.reveal == "by_line":
            return 0.4 * self._line_count(scene) + 1.5
        return 2.0

    def layout(self, scene: CodeScene, aspect: Aspect):
        w, h = size_of(aspect)
        vertical = aspect == "9x16"
        margin = 50 if vertical else 90
        chrome = 70
        lines, bg, fg = tokenize(scene.code, scene.language, self.env.style.code_theme)
        size = 42 if vertical else 48
        while True:
            fnt = draw.font(self.env.style.mono_font, size)
            char_w = fnt.getlength("M")
            max_cols = int((w - 2 * margin - 60) // char_w)
            rows = wrap_rows(lines, max_cols if vertical else max(max_cols, 20))
            line_h = int(size * 1.45)
            fits = len(rows) * line_h <= h - 2 * margin - chrome - 40
            wrapped = any(r.continuation for r in rows)
            # 16:9 — сначала уменьшаем шрифт, перенос только если и 30px не влезает; 9:16 — переносим
            if (fits and (vertical or not wrapped or size <= 30)) or size <= 18:
                break
            size -= 2
        return dict(
            w=w,
            h=h,
            margin=margin,
            chrome=chrome,
            rows=rows,
            bg=bg,
            fg=fg,
            font=fnt,
            line_h=line_h,
            vertical=vertical,
        )

    def compose(
        self, scene: CodeScene, lay: dict, visible_lines: int, highlight: bool, out: Path
    ) -> Path:
        st = self.env.style
        img = draw.canvas((lay["w"], lay["h"]), st)
        d = ImageDraw.Draw(img)
        m, w, h = lay["margin"], lay["w"], lay["h"]
        body_h = len(lay["rows"]) * lay["line_h"] + 60
        free = h - body_h - lay["chrome"]
        win_top = max(m, free // 3 if lay["vertical"] else free // 2)
        win_bottom = min(h - m, win_top + lay["chrome"] + body_h)
        d.rounded_rectangle([m, win_top, w - m, win_bottom], radius=24, fill=lay["bg"])
        for i, color in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
            cx = m + 40 + i * 34
            d.ellipse([cx - 11, win_top + 24, cx + 11, win_top + 46], fill=draw.rgb(color))
        label_font = draw.font(st.font, 26)
        d.text((m + 150, win_top + 20), scene.language, font=label_font, fill=draw.rgb(st.muted))
        y = win_top + lay["chrome"] + 20
        x0 = m + 40
        hl = set(scene.highlight_lines) if highlight else set()
        for row in lay["rows"]:
            if row.line_no > visible_lines:
                break
            if row.line_no in hl:
                d.rectangle(
                    [m + 8, y - 4, w - m - 8, y + lay["line_h"] - 6], fill=draw.rgb(st.highlight_bg)
                )
                d.rectangle([m + 8, y - 4, m + 16, y + lay["line_h"] - 6], fill=draw.rgb(st.accent))
            x = x0
            for text, color, _bold in row.tokens:
                d.text((x, y), text, font=lay["font"], fill=color)
                x += lay["font"].getlength(text)
            y += lay["line_h"]
        return draw.save(img, out)

    def timeline(self, scene: CodeScene, duration: float) -> list[tuple[int, bool, float]]:
        """[(видимых строк, подсветка, длительность)]."""
        n = self._line_count(scene)
        has_hl = bool(scene.highlight_lines)
        if scene.reveal == "all":
            if not has_hl:
                return [(n, False, duration)]
            first = min(max(duration * 0.25, 0.8), duration / 2)
            return [(n, False, first), (n, True, duration - first)]
        step = min(LINE_STEP, max(duration * 0.75 / n, 0.2))
        frames = [(k, False, step) for k in range(1, n)]
        rest = max(duration - step * (n - 1), 0.5)
        if has_hl:
            first = min(1.0, rest / 2)
            frames += [(n, False, first), (n, True, rest - first)]
        else:
            frames.append((n, False, rest))
        return frames

    def render(self, scene: CodeScene, aspect: Aspect, duration_hint: float) -> SceneRender:
        lay = self.layout(scene, aspect)
        sdir = self.env.scene_dir(scene.id) / f"frames_{aspect}"
        frames = []
        for i, (visible, hl, dur) in enumerate(self.timeline(scene, max(duration_hint, 1.0))):
            frames.append((self.compose(scene, lay, visible, hl, sdir / f"f{i:03d}.png"), dur))
        out = self.env.visual_path(scene.id, aspect)
        frames_to_video(frames, out, aspect, self.env.encoder)
        return finish(self.env, scene.id, aspect, out)
