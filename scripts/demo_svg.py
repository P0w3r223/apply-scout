"""Render a recorded terminal cast as a self-contained animated SVG.

Pure functions only — cast in, SVG string out — so the rendering is unit-tested and
deterministic: the same cast always produces byte-identical SVG.

Why SVG and not a GIF: it is text, so it diffs and reviews like code, it stays crisp at
any zoom, it needs no recorder binary (nothing to install on Windows), and GitHub renders
it in the README. The animation is plain CSS keyframes — no script, which is what keeps it
working when GitHub serves the file as an ``<img>``.

The terminal chrome is drawn dark on purpose: it reads the same in GitHub's light and dark
themes instead of inverting with them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

# --- Layout (a fixed character grid; monospace advance width at FONT_SIZE) ----
COLS = 100
ROWS = 24  # the window is a fixed size; longer output scrolls, exactly like a terminal
FONT_SIZE = 14.0
CHAR_W = 8.4
LINE_H = 19.0
PAD = 18.0
TITLE_H = 34.0
FONT_STACK = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'DejaVu Sans Mono', monospace"
# A single step can print a page (the final model call *is* the report). Cap what one
# frame contributes to the stream, and say how much was cut — except for the last frame,
# which is the payoff and was already trimmed where it was recorded.
MAX_FRAME_ROWS = 6

# --- Pacing ------------------------------------------------------------------
# Real gaps between steps are minutes-long in places (a model call, then eighteen HTTP
# round-trips). Clamping keeps the recording honest in *order* while making it watchable:
# the animation is a demo, not a stopwatch. Stated in the README caption too.
MIN_DELAY_S = 0.18
MAX_DELAY_S = 1.30
PROMPT_HOLD_S = 0.9  # after the command line, before the first step
END_HOLD_S = 3.5  # let the summary sit on screen before the loop restarts

# --- Colours (GitHub-dark-ish; keys are the rich styles from formatting.py) ---
BACKGROUND = "#0d1117"
CHROME = "#161b22"
BORDER = "#30363d"
FOREGROUND = "#c9d1d9"
PROMPT_COLOR = "#3fb950"
STYLE_COLORS = {
    "": FOREGROUND,
    "cyan": "#56d4dd",
    "dim": "#8b949e",
    "red": "#f85149",
    "bold green": "#3fb950",
    "bold yellow": "#d29922",
}
BOLD_STYLES = frozenset({"bold green", "bold yellow"})


@dataclass(frozen=True)
class Frame:
    """One printed chunk of the run: what was printed, when, and how it was styled.

    ``group`` is the collapse key — repeated tool calls share one, so a run that makes
    eighteen identical-shaped calls can be shown as three plus a count.
    """

    t: float
    text: str
    style: str = ""
    group: str | None = None


@dataclass(frozen=True)
class Cast:
    command: str
    frames: tuple[Frame, ...]
    title: str = "apply-scout"

    @classmethod
    def from_dict(cls, data: dict) -> Cast:
        frames = tuple(
            Frame(
                t=float(f["t"]),
                text=str(f["text"]),
                style=str(f.get("style") or ""),
                group=f.get("group"),
            )
            for f in data["frames"]
        )
        return cls(
            command=str(data["command"]),
            frames=frames,
            title=str(data.get("title") or "apply-scout"),
        )

    @classmethod
    def load(cls, path: Path) -> Cast:
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class Line:
    """A single rendered row of the terminal, with the time it appears."""

    text: str
    style: str
    at: float


def wrap(text: str, cols: int = COLS) -> list[str]:
    """Wrap to the character grid, keeping each source line's indentation on its runs.

    Long single tokens (URLs) are cut rather than allowed to overflow the window — a
    terminal does the same.
    """
    rows: list[str] = []
    for raw in text.split("\n"):
        indent = " " * (len(raw) - len(raw.lstrip(" ")))
        remaining, first = raw.strip("\n"), True
        if not remaining.strip():
            rows.append("")
            continue
        while remaining:
            prefix = "" if first else indent
            budget = max(cols - len(prefix), 8)
            if len(remaining) <= budget:
                rows.append(prefix + remaining)
                break
            cut = remaining.rfind(" ", 0, budget + 1)
            if cut <= len(indent):  # no break point: hard-cut the token
                cut = budget
            rows.append(prefix + remaining[:cut].rstrip())
            remaining = remaining[cut:].lstrip(" ")
            first = False
    return rows


def collapse(frames: tuple[Frame, ...], keep: int = 3) -> list[Frame]:
    """Replace long runs of same-``group`` frames with the first ``keep`` and a count.

    Honest elision: the count says exactly how many were dropped, so nobody reads the
    demo as "the agent made three calls".
    """
    out: list[Frame] = []
    index = 0
    while index < len(frames):
        frame = frames[index]
        if frame.group is None:
            out.append(frame)
            index += 1
            continue
        run_end = index
        while run_end < len(frames) and frames[run_end].group == frame.group:
            run_end += 1
        run = frames[index:run_end]
        out.extend(run[:keep])
        hidden = len(run) - keep
        if hidden > 0:
            last = run[-1]
            out.append(
                Frame(
                    t=last.t,
                    text=f"    ... {hidden} more {frame.group} call(s), same shape",
                    style="dim",
                )
            )
        index = run_end
    return out


def _trim(rows: list[str], max_rows: int) -> list[str]:
    """Keep the first ``max_rows`` rows and count what was dropped."""
    if len(rows) <= max_rows:
        return rows
    indent = " " * (len(rows[0]) - len(rows[0].lstrip(" ")))
    return [*rows[:max_rows], f"{indent}... {len(rows) - max_rows} more line(s)"]


def layout(cast: Cast, cols: int = COLS) -> list[Line]:
    """Turn a cast into timed terminal rows: the command line, then the clamped stream."""
    # The command carries a URL, so it wraps like any other row — only its first row
    # gets the prompt marker.
    command_rows = wrap(cast.command, cols - 2)
    lines = [Line(text=f"$ {command_rows[0]}", style="prompt", at=0.0)]
    lines += [Line(text=f"  {row}", style="", at=0.0) for row in command_rows[1:]]
    clock = PROMPT_HOLD_S
    previous_t: float | None = None
    frames = collapse(cast.frames)
    for index, frame in enumerate(frames):
        if previous_t is not None:
            clock += min(max(frame.t - previous_t, MIN_DELAY_S), MAX_DELAY_S)
        previous_t = frame.t
        rows = wrap(frame.text, cols)
        if index < len(frames) - 1:
            rows = _trim(rows, MAX_FRAME_ROWS)
        lines.extend(Line(text=row, style=frame.style, at=clock) for row in rows)
    return lines


def scroll_offsets(lines: list[Line], rows: int = ROWS) -> list[tuple[float, int]]:
    """How far the stream has scrolled up at each cue, in rows.

    A terminal keeps the newest output on screen: once more rows exist than fit, the
    window follows the tail. Returned as (cue time, rows scrolled), deduplicated so a
    cue that changes nothing costs no keyframe.
    """
    cues = sorted({line.at for line in lines})
    offsets: list[tuple[float, int]] = []
    for cue in cues:
        revealed = sum(1 for line in lines if line.at <= cue)
        offset = max(0, revealed - rows)
        if not offsets or offsets[-1][1] != offset:
            offsets.append((cue, offset))
    return offsets


def _keyframes(index: int, at: float, total: float) -> str:
    """A per-line reveal that survives the loop: hidden until its cue, then held to the end."""
    cue = round(at / total * 100, 3)
    lit = min(cue + 0.35, 100)
    return (
        f"@keyframes r{index}{{0%,{cue}%{{opacity:0}}{lit:.3f}%,100%{{opacity:1}}}}"
        f".r{index}{{animation:r{index} {total:.2f}s linear infinite}}"
    )


def _scroll_rules(lines: list[Line], total: float, rows: int) -> str:
    """Keyframes that walk the stream upward, one glide per cue that moves it."""
    offsets = scroll_offsets(lines, rows)
    if len(offsets) < 2:
        return ""
    stops, previous = [], 0
    for cue, offset in offsets:
        percent = round(cue / total * 100, 3)
        settled = min(percent + 1.0, 100)
        stops.append(f"{percent}%{{transform:translateY({-previous * LINE_H:.0f}px)}}")
        stops.append(f"{settled:.3f}%{{transform:translateY({-offset * LINE_H:.0f}px)}}")
        previous = offset
    stops.append(f"100%{{transform:translateY({-previous * LINE_H:.0f}px)}}")
    return (
        f"@keyframes scroll{{{''.join(stops)}}}"
        f".stream{{animation:scroll {total:.2f}s linear infinite}}"
    )


def render_svg(cast: Cast, cols: int = COLS, rows: int = ROWS) -> str:
    """The whole picture: window chrome plus one animated <text> per terminal row.

    The window is a fixed ``rows``-tall viewport; anything longer scrolls under a clip,
    so a two-minute run and a ten-second one produce the same size image.
    """
    lines = layout(cast, cols)
    total = max((line.at for line in lines), default=0.0) + END_HOLD_S
    width = round(PAD * 2 + cols * CHAR_W, 1)
    height = round(TITLE_H + PAD * 2 + rows * LINE_H, 1)

    cues = sorted({line.at for line in lines})
    cue_class = {at: index for index, at in enumerate(cues)}
    rules = "".join(_keyframes(index, at, total) for at, index in cue_class.items())

    body = []
    for row, line in enumerate(lines):
        y = TITLE_H + PAD + (row + 0.8) * LINE_H
        klass = f"r{cue_class[line.at]}"
        if line.style == "prompt":
            body.append(
                f'<text class="{klass}" x="{PAD}" y="{y:.1f}">'
                f'<tspan fill="{PROMPT_COLOR}">$</tspan>'
                f'<tspan fill="{FOREGROUND}"> {escape(line.text[2:])}</tspan></text>'
            )
            continue
        weight = ' font-weight="bold"' if line.style in BOLD_STYLES else ""
        fill = STYLE_COLORS.get(line.style, FOREGROUND)
        body.append(
            f'<text class="{klass}" x="{PAD}" y="{y:.1f}" fill="{fill}"{weight}>'
            f"{escape(line.text)}</text>"
        )

    dots = "".join(
        f'<circle cx="{x}" cy="{TITLE_H / 2:.0f}" r="5.5" fill="{color}"/>'
        for x, color in ((22, "#ff5f56"), (42, "#ffbd2e"), (62, "#27c93f"))
    )
    viewport_top = TITLE_H
    viewport_h = height - TITLE_H
    # Rounded top corners for the title bar, drawn over the stream so scrolled rows
    # disappear behind it rather than under the window edge.
    bar = f"M0 10a10 10 0 0 1 10-10h{width - 20:.1f}a10 10 0 0 1 10 10v{TITLE_H - 10:.0f}H0z"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{escape(cast.title)} terminal demo">'
        f"<style>text{{font-family:{FONT_STACK};font-size:{FONT_SIZE}px;"
        f"white-space:pre;opacity:0}}{rules}{_scroll_rules(lines, total, rows)}</style>"
        f'<clipPath id="viewport"><rect x="0" y="{viewport_top}" width="{width}" '
        f'height="{viewport_h}"/></clipPath>'
        f'<rect width="{width}" height="{height}" rx="10" fill="{BACKGROUND}" '
        f'stroke="{BORDER}"/>'
        f'<g clip-path="url(#viewport)"><g class="stream">{"".join(body)}</g></g>'
        f'<path d="{bar}" fill="{CHROME}"/>'
        f"{dots}"
        f'<text x="{width / 2:.1f}" y="{TITLE_H / 2 + 4:.0f}" fill="#8b949e" text-anchor="middle" '
        f'style="opacity:1">{escape(cast.title)}</text>'
        "</svg>"
    )
