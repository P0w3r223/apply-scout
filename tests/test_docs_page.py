"""The published page — specifically, what carries the recording.

Nothing else here covers `docs/index.html`, which is how the defect below survived: an
`<img>` pointing at a file that exists, served with a 200, raising no console error. The
page simply showed nothing, and only a person looking at it could tell.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
EXPECTED = ROOT / "eval" / "expected"


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


def _completion_rates() -> set[str]:
    """The `Completed` column of every committed expected table, as it is printed."""
    rates: set[str] = set()
    for table in sorted(EXPECTED.glob("*.md")):
        for line in table.read_text(encoding="utf-8").splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) > 2 and cells[2].endswith("%"):
                rates.add(cells[2])
    return rates


def test_the_page_explains_the_completion_rate_the_tables_report():
    """The page's prose must not contradict the artifact printed directly above it.

    It did, in public, for twelve days. Milestone 17 moved both pipeline rows 75% → 62% so all
    three runners answered one question, and the table on this page moved with them — but the
    paragraph beneath it went on saying "Completion is 75% rather than 100% because two of the
    eight advertisements were taken down". A reader saw 62% in the table and 75% in the sentence
    explaining it, on the flagship's page, with the true figure sitting in `eval/expected/`
    the whole time.

    The number is read from the committed tables rather than pinned here, so re-recording the
    eval moves the assertion with it and this fails only when the prose is the thing left behind.
    """
    rates = _completion_rates()
    assert rates, "no completion rate found in eval/expected — the source of truth moved"

    claimed = re.findall(r"Completion is (\d+%) rather than 100%", PAGE)
    assert claimed, "the page no longer explains its completion rate at all"
    stale = sorted(set(claimed) - rates)
    assert not stale, (
        f"the page explains a completion rate of {stale} that no committed table reports "
        f"(they report {sorted(rates)}) — re-read docs/index.html against eval/expected/"
    )
