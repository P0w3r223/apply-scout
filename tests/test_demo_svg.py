"""The demo renderer: cast in, animated SVG out (pure, so it is pinned by tests)."""

from __future__ import annotations

from pathlib import Path

import pytest
from demo_svg import (
    COLS,
    MAX_FRAME_ROWS,
    ROWS,
    Cast,
    Frame,
    collapse,
    layout,
    render_svg,
    scroll_offsets,
    wrap,
)

DOCS = Path(__file__).resolve().parents[1] / "docs"


def _cast(*frames: Frame) -> Cast:
    return Cast(command="apply-scout run --url https://example.com", frames=frames)


def test_the_committed_svg_is_what_its_cast_renders_to():
    """The README shows a generated picture. If the renderer or the cast moves and the SVG
    is not regenerated, the page starts lying — so pin them together."""
    cast_path, svg_path = DOCS / "demo-cast.json", DOCS / "demo.svg"
    if not cast_path.exists():
        pytest.skip("no demo recorded yet")
    assert svg_path.read_text(encoding="utf-8") == render_svg(Cast.load(cast_path)) + "\n"


def test_wrap_keeps_indentation_on_continuation_rows():
    rows = wrap("    - github_evidence -> ok: " + "word " * 40, cols=60)
    assert len(rows) > 1
    assert all(len(row) <= 60 for row in rows)
    assert all(row.startswith("    ") for row in rows)


def test_wrap_hard_cuts_a_token_longer_than_the_grid():
    rows = wrap("https://example.com/" + "x" * 200, cols=40)
    assert max(len(row) for row in rows) == 40


def test_collapse_keeps_the_first_calls_and_counts_the_rest():
    frames = tuple(
        Frame(
            t=float(i),
            text=f"    - github_evidence -> ok: q{i}",
            style="dim",
            group="github_evidence",
        )
        for i in range(10)
    )
    collapsed = collapse(frames, keep=3)
    assert len(collapsed) == 4
    assert "7 more github_evidence call(s)" in collapsed[-1].text


def test_collapse_leaves_ungrouped_frames_alone():
    frames = (
        Frame(t=0.0, text="[0] model", style="cyan"),
        Frame(t=1.0, text="    - read_cv -> ok", style="dim", group="read_cv"),
        Frame(t=2.0, text="[1] model", style="cyan"),
    )
    assert collapse(frames) == list(frames)


def test_layout_clamps_real_gaps_but_keeps_order():
    lines = layout(
        _cast(Frame(t=0.0, text="a"), Frame(t=600.0, text="b"), Frame(t=600.01, text="c"))
    )
    reveal = [line.at for line in lines]
    assert reveal == sorted(reveal)
    assert reveal[-1] - reveal[1] < 3.0  # a ten-minute gap does not become a ten-minute animation


def test_render_escapes_markup_and_is_deterministic():
    cast = _cast(Frame(t=0.0, text="tool <input> & 'args'", style="dim"))
    svg = render_svg(cast)
    assert svg == render_svg(cast)
    assert "<input>" not in svg
    assert "&lt;input&gt; &amp;" in svg


def test_render_animates_every_row_without_script():
    cast = _cast(
        Frame(t=0.0, text="[0] model", style="cyan"),
        Frame(t=1.0, text="[done]", style="bold green"),
    )
    svg = render_svg(cast)
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "<script" not in svg  # GitHub serves this as an <img>: CSS animates, JS would not run
    assert svg.count("@keyframes") == 3  # command line + two frames
    assert 'font-weight="bold"' in svg


def test_no_rendered_row_overflows_the_grid():
    long_url = "https://jobs.example.com/" + "a" * 90
    cast = Cast(
        command=f"apply-scout run --url {long_url} --cv cv/candidate.md --verbose",
        frames=(
            Frame(t=0.0, text="    - fetch_job_posting -> ok: " + "detail " * 30, style="dim"),
        ),
    )
    assert all(len(line.text) <= COLS for line in layout(cast))


def test_render_grid_is_wide_enough_for_the_widest_row():
    long_row = "x" * (COLS - 1)
    svg = render_svg(_cast(Frame(t=0.0, text=long_row)))
    assert long_row in svg


def test_a_page_long_frame_is_trimmed_with_a_count():
    page = "\n".join(f"    line {i}" for i in range(30))
    lines = layout(_cast(Frame(t=0.0, text=page), Frame(t=1.0, text="[done]", style="bold green")))
    trimmed = [line.text for line in lines if "more line(s)" in line.text]
    assert trimmed == [f"    ... {30 - MAX_FRAME_ROWS} more line(s)"]


def test_the_last_frame_is_shown_as_recorded():
    page = "\n".join(f"row {i}" for i in range(30))
    lines = layout(_cast(Frame(t=0.0, text="[0] model", style="cyan"), Frame(t=1.0, text=page)))
    assert "row 29" in [line.text for line in lines]


def test_the_window_follows_the_tail_once_output_overflows():
    frames = tuple(Frame(t=float(i), text=f"[{i}] model", style="cyan") for i in range(ROWS + 10))
    lines = layout(_cast(*frames))
    offsets = scroll_offsets(lines, ROWS)
    assert offsets[0][1] == 0  # nothing scrolls while it still fits
    assert offsets[-1][1] == len(lines) - ROWS  # the last rows end up on screen


def test_window_height_is_fixed_however_long_the_run_is():
    short = render_svg(_cast(Frame(t=0.0, text="[0] model", style="cyan")))
    frames = tuple(Frame(t=float(i), text=f"[{i}] model", style="cyan") for i in range(60))
    long_run = render_svg(_cast(*frames))

    def height(svg: str) -> str:
        return svg.split('height="', 1)[1].split('"', 1)[0]

    assert height(short) == height(long_run)
    assert "@keyframes scroll" in long_run
    assert "@keyframes scroll" not in short  # a short run has nothing to scroll
