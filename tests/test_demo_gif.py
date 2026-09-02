"""The GIF renderer: the same cast, drawn for the readers an SVG never animates for.

`test_demo_svg.py` pins the SVG byte-for-byte against what its cast renders to, which
works because an SVG is text. A GIF is a rasterisation — it depends on the Pillow and
FreeType builds doing the drawing — so the equivalent assertion would fail between CI and
a laptop for reasons that say nothing about the picture being right.

What is pinned instead is what can actually go wrong: the cast moving on while the
committed GIF stays behind. Frame count and geometry both come from the cast, so a
re-recorded run that nobody re-rendered fails here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from demo_svg import COLS, END_HOLD_S, LINE_H, PAD, ROWS, TITLE_H, Cast, Frame, layout

pytest.importorskip("PIL", reason="Pillow is a dev dependency; it renders docs, not the agent")

from demo_gif import CHAR_W, frame_plan, offset_at, render_gif  # noqa: E402

DOCS = Path(__file__).resolve().parents[1] / "docs"


def _cast(*frames: Frame) -> Cast:
    return Cast(command="apply-scout run --url https://example.com", frames=frames)


def test_the_committed_gif_still_matches_its_cast():
    """A re-recorded run with a stale picture beside it is the failure this catches.

    Not compared byte for byte: the rasteriser is allowed to differ between machines. The
    frame count is a property of the cast, so it moves the moment the recording does.
    """
    cast_path, gif_path = DOCS / "demo-cast.json", DOCS / "demo.gif"
    if not cast_path.exists() or not gif_path.exists():
        pytest.skip("no demo recorded yet")
    from PIL import Image

    cast = Cast.load(cast_path)
    expected = len(frame_plan(layout(cast)))
    with Image.open(gif_path) as image:
        assert image.n_frames == expected, (
            "docs/demo.gif holds a different number of frames than the cast renders to; "
            "re-run `python scripts/demo.py render-gif`"
        )
        assert image.size == (
            round(PAD * 2 + COLS * CHAR_W),
            round(TITLE_H + PAD * 2 + ROWS * LINE_H),
        )


def test_every_cue_becomes_exactly_one_frame():
    """An SVG can skip a cue that changes nothing; a GIF draws every frame whole."""
    cast = _cast(Frame(t=0.0, text="first"), Frame(t=1.0, text="second"),
                 Frame(t=2.0, text="third"))
    lines = layout(cast)
    assert len(frame_plan(lines)) == len({line.at for line in lines})


def test_the_last_frame_holds_so_the_summary_can_be_read():
    """The SVG builds the same pause into its total duration before the loop restarts."""
    plan = frame_plan(layout(_cast(Frame(t=0.0, text="a"), Frame(t=1.0, text="b"))))
    assert plan[-1][2] == END_HOLD_S
    assert all(hold < END_HOLD_S for _, _, hold in plan[:-1])


def test_the_scroll_offset_is_carried_between_the_cues_that_change_it():
    """`scroll_offsets` reports only the cues that move the window; a GIF needs all of them."""
    offsets = [(0.0, 0), (2.0, 3), (5.0, 7)]
    assert offset_at(offsets, 0.0) == 0
    assert offset_at(offsets, 1.9) == 0
    assert offset_at(offsets, 2.0) == 3
    assert offset_at(offsets, 4.9) == 3
    assert offset_at(offsets, 99.0) == 7


def test_a_rendered_gif_animates_rather_than_holding_one_still(tmp_path):
    """The defect that started this: a picture that exists, loads, and never moves."""
    out = tmp_path / "demo.gif"
    frames = render_gif(_cast(Frame(t=0.0, text="one"), Frame(t=1.0, text="two"),
                              Frame(t=2.0, text="three")), out)
    from PIL import Image

    assert frames > 1
    with Image.open(out) as image:
        assert image.n_frames == frames
        assert image.is_animated
