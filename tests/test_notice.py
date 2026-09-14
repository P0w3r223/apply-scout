"""NOTICE, held to the recordings it carves out of the MIT grant.

`LICENSE` grants MIT over the whole tree and `eval/cassettes/` redistributes five
companies' job-board pages verbatim. `docs/decisions/0004` §Consequences discloses that
data plainly — *"a ~1.5 MB data artifact of third-party responses, including raw posting
HTML"* — so the gap was never disclosure. It was that no file reconciled the recordings
with the grant, and a reader taking the repository at its licence would have taken those
pages with it.

A hand-written carve-out is worth exactly as much as its list is current, and the list
goes stale the first time someone re-records. So the note names no count and the guards
below derive both directions from the cassettes themselves: a page recorded and not
listed, or listed and not recorded, is a failure here rather than a discovery later.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTICE = ROOT / "NOTICE"
#: Both, because `run.jsonl` records the demo against a posting of its own. A guard
#: reading only the evaluation's cassette would let a page enter the tree unlisted.
CASSETTES = (
    ROOT / "eval" / "cassettes" / "eval.jsonl",
    ROOT / "eval" / "cassettes" / "run.jsonl",
)
#: The sentence opening the second list. Everything above it kept page content.
REFUSED_MARKER = "These were recorded and answered HTTP 404."


def _recorded() -> dict[str, bool]:
    """Every URL an `http` record holds, mapped to whether it kept page content."""
    found: dict[str, bool] = {}
    for path in CASSETTES:
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("kind") != "http":
                continue
            url, payload = record["label"], record["payload"]
            # Two keys and no third: a retrieved page is `html`, a refusal is `error`.
            # Asserting that partition rather than assuming it is what stops a shape
            # nobody anticipated being filed as "kept nothing" — the reading that would
            # quietly excuse a page from the list. The first edition of this guard tested
            # `isinstance(payload, str)` and every record failed it, which is the cheapest
            # way this file could have found out that both shapes are dicts.
            keys = sorted(payload)
            assert keys in (["error"], ["html"]), f"{url}: unrecognised payload shape {keys}"
            found[url] = keys == ["html"]
    return found


def _listed() -> dict[str, bool]:
    """Every URL the note names, mapped to which of its two lists it sits in."""
    text = NOTICE.read_bytes().decode("utf-8")
    assert REFUSED_MARKER in text, (
        "NOTICE must keep the two lists apart; without that sentence this guard cannot "
        "tell a page it kept from a 404 it did not"
    )
    cut = text.index(REFUSED_MARKER)
    kept = re.findall(r"https://\S+", text[:cut])
    refused = re.findall(r"https://\S+", text[cut:])
    listed = {url: True for url in kept}
    listed.update(dict.fromkeys(refused, False))
    assert len(listed) == len(kept) + len(refused), "NOTICE lists a URL twice"
    return listed


def test_the_notice_lists_exactly_the_urls_the_cassettes_recorded():
    """Both directions, because each fails differently.

    A recorded page missing from the note is the finding this file exists for. A note
    naming a URL no cassette holds is the other half: it attributes content to a publisher
    whose page is not in the tree, which is the mistake `0010` A-2 warned a repair here
    could make with the two 404s.
    """
    recorded = _recorded()
    # Without this the whole guard passes on an empty tree — two empty sets agree.
    assert recorded, "no http records found; this guard is reading the wrong files"
    assert _listed() == recorded


def test_and_it_tells_the_pages_it_kept_from_the_ones_that_answered_404():
    """The classification, asserted as a property rather than trusted to the test above.

    Dict equality already compares it, but only while both classes are present: if every
    record were a page, the mapping would be all-`True` on both sides and a note that had
    silently moved a URL between its lists would still read green. This says the corpus
    still has one of each, so that comparison is doing work.
    """
    recorded = _recorded()
    kept = [url for url, page in recorded.items() if page]
    refused = [url for url, page in recorded.items() if not page]
    assert kept and refused, (
        f"the cassettes must hold both a kept page and a 404 for the note's two lists to "
        f"mean anything; got {len(kept)} kept, {len(refused)} refused"
    )


def test_the_note_says_what_it_carves_out_and_from_which_grant():
    """The claim itself, which the URL lists do not make.

    A NOTICE reduced to two lists of links would pass everything above it and grant
    nothing. These are the three names the carve-out is written in terms of, so deleting
    the sentence that does the work fails here rather than reading as a formatting change.
    """
    text = NOTICE.read_bytes().decode("utf-8")
    for phrase in ("LICENSE", "eval/cassettes/", "docs/decisions/0004"):
        assert phrase in text, f"NOTICE must name {phrase}"
