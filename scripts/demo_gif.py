"""Cast -> animated GIF, for the readers an SVG never animates for.

`demo_svg.py` is the better picture: text, a few kilobytes, crisp at any zoom. It is also
invisible in two of the three places this demo is read. A browser renders an SVG loaded by
`<img>` as a static image and never starts its stylesheet's animations, and GitHub
sanitises HTML out of a README, so `<object>` — the fix on the published page — is not
available there. Every row of the recording begins at `opacity: 0`, so in a README the
whole thing is a black rectangle.

A GIF animates in all three. It is the worse format and it is the one that works, so both
are generated from the same cast: this module imports the layout, the timing and the
palette from `demo_svg` rather than restating them, which is what keeps the two pictures
from drifting into two different accounts of the same run.

The font is vendored beside this file. Left to a system font the same command would draw a
different picture on every machine, and the point of generating from a recording is that
anyone can regenerate it and get what is committed.
"""

from __future__ import annotations

from pathlib import Path

from demo_svg import (
    BACKGROUND,
    BORDER,
    CHAR_W,
    CHROME,
    COLS,
    END_HOLD_S,
    FONT_SIZE,
    FOREGROUND,
    LINE_H,
    PAD,
    PROMPT_COLOR,
    ROWS,
    STYLE_COLORS,
    TITLE_H,
    Cast,
    Line,
    layout,
    scroll_offsets,
)
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = Path(__file__).with_name("assets") / "DejaVuSansMono.ttf"
TITLE_COLOR = "#8b949e"
DOTS = ((22, "#ff5f56"), (42, "#ffbd2e"), (62, "#27c93f"))
CORNER = 10

# A GIF stores hundredths of a second, so anything finer is rounded away by the format
# itself. Frames are held at least this long: a cue that lands 20ms after another would
# otherwise round to zero and be dropped by some decoders.
MIN_HOLD_S = 0.04
PALETTE_COLORS = 32  # the terminal uses six ink colours and three window ones


def _size(cols: int = COLS, rows: int = ROWS) -> tuple[int, int]:
    """The SVG's own geometry, rounded to whole pixels."""
    return round(PAD * 2 + cols * CHAR_W), round(TITLE_H + PAD * 2 + rows * LINE_H)


def offset_at(offsets: list[tuple[float, int]], cue: float) -> int:
    """How far the stream has scrolled at ``cue``.

    `scroll_offsets` reports only the cues that *move* the window, because a keyframe that
    changes nothing is wasted in an SVG. A GIF draws every frame whole, so each one needs
    the offset in force at its moment, which is the last change at or before it.
    """
    current = 0
    for at, offset in offsets:
        if at > cue:
            break
        current = offset
    return current


def frame_plan(lines: list[Line], rows: int = ROWS) -> list[tuple[float, int, float]]:
    """One (cue, scroll offset, hold in seconds) per frame the GIF will draw.

    The last frame holds for `END_HOLD_S` so the summary can be read before the loop
    restarts — the same pause the SVG builds into its total duration.
    """
    cues = sorted({line.at for line in lines})
    offsets = scroll_offsets(lines, rows)
    plan: list[tuple[float, int, float]] = []
    for index, cue in enumerate(cues):
        following = cues[index + 1] if index + 1 < len(cues) else None
        hold = END_HOLD_S if following is None else max(following - cue, MIN_HOLD_S)
        plan.append((cue, offset_at(offsets, cue), hold))
    return plan


def _draw_chrome(
    draw: ImageDraw.ImageDraw, title: str, width: int, font: ImageFont.FreeTypeFont
) -> None:
    """The title bar, drawn last so scrolled rows disappear behind it."""
    draw.rounded_rectangle([0, 0, width - 1, TITLE_H], radius=CORNER, fill=CHROME)
    # rounded_rectangle rounds all four corners; the bar's bottom edge is square.
    draw.rectangle([0, TITLE_H - CORNER, width - 1, TITLE_H], fill=CHROME)
    for x, colour in DOTS:
        draw.ellipse([x - 5.5, TITLE_H / 2 - 5.5, x + 5.5, TITLE_H / 2 + 5.5], fill=colour)
    draw.text((width / 2, TITLE_H / 2), title, font=font, fill=TITLE_COLOR, anchor="mm")


def render_frame(
    lines: list[Line],
    cue: float,
    offset: int,
    title: str,
    font: ImageFont.FreeTypeFont,
    cols: int = COLS,
    rows: int = ROWS,
) -> Image.Image:
    """The terminal as it stood at ``cue``: every row revealed by then, scrolled by ``offset``."""
    width, height = _size(cols, rows)
    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([0, 0, width - 1, height - 1], radius=CORNER,
                           fill=BACKGROUND, outline=BORDER)

    for row, line in enumerate(lines):
        if line.at > cue:
            break
        y = TITLE_H + PAD + (row - offset + 0.8) * LINE_H
        if y < TITLE_H or y > height:  # clipped by the viewport, exactly as in the SVG
            continue
        if line.style == "prompt":
            draw.text((PAD, y), "$", font=font, fill=PROMPT_COLOR, anchor="ls")
            draw.text((PAD + CHAR_W, y), line.text[1:], font=font, fill=FOREGROUND,
                      anchor="ls")
            continue
        draw.text((PAD, y), line.text, font=font,
                  fill=STYLE_COLORS.get(line.style, FOREGROUND), anchor="ls")

    _draw_chrome(draw, title, width, font)
    return image


def render_gif(cast: Cast, path: Path, cols: int = COLS, rows: int = ROWS) -> int:
    """Write the animated GIF and return how many frames it holds."""
    lines = layout(cast, cols)
    plan = frame_plan(lines, rows)
    font = ImageFont.truetype(str(FONT_PATH), round(FONT_SIZE))

    frames = [
        render_frame(lines, cue, offset, cast.title, font, cols, rows).quantize(
            colors=PALETTE_COLORS, dither=Image.Dither.NONE
        )
        for cue, offset, _ in plan
    ]
    durations = [round(hold * 1000) for _, _, hold in plan]

    path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=1,  # each frame is drawn whole over the last; no transparency to clear
    )
    return len(frames)
