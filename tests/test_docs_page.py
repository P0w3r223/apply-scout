"""The published page — specifically, what carries the recording.

Nothing else here covers `docs/index.html`, which is how the defect below survived: an
`<img>` pointing at a file that exists, served with a 200, raising no console error. The
page simply showed nothing, and only a person looking at it could tell.
"""

from __future__ import annotations

from pathlib import Path

PAGE = (Path(__file__).resolve().parents[1] / "docs" / "index.html").read_text(encoding="utf-8")


def test_the_recording_is_not_embedded_as_an_image():
    """`demo.svg` animates through CSS keyframes, and every row of it starts at opacity 0.

    Chrome loads an SVG referenced by `<img>` as a static image and never starts its
    stylesheet's animations, so embedded that way the page's only evidence is a black
    rectangle for the whole visit. An `<object>` loads the same file as a document, where
    the keyframes run. `demo_svg.py` deliberately animates without script, so the fix
    belongs here, at the embed, rather than in the renderer.
    """
    assert '<img src="demo.svg"' not in PAGE, (
        "the recording is embedded as an image again — Chrome will not animate it there"
    )
    assert 'data="demo.svg"' in PAGE, "the page no longer embeds the recording at all"
