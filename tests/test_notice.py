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
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
NOTICE = ROOT / "NOTICE"
#: Every cassette, derived. `run.jsonl` records the demo against a posting of its own and
#: arrived after `eval.jsonl`, so a third is an ordinary thing for this repository to gain
#: — and the first edition of this file answered that by naming the two it knew about,
#: which is the hand-maintained registry the note itself refuses to keep. A review caught
#: it by dropping a third cassette in and watching all three tests stay green.
CASSETTE_DIR = ROOT / "eval" / "cassettes"
#: The sentence opening the second list. Everything above it kept page content.
REFUSED_MARKER = "These were recorded and answered HTTP 404."
#: Which board serves each host, so the note's middle column answers to the URL rather
#: than to whoever typed it. Not derivable — a hostname does not spell its product — so it
#: is pinned, and a host absent from here fails rather than being skipped.
BOARD_BY_HOST = {
    "jobs.smartrecruiters.com": "SmartRecruiters",
    "jobs.lever.co": "Lever",
    "jobs.ashbyhq.com": "Ashby",
    "job-boards.greenhouse.io": "Greenhouse",
}


def _notice() -> str:
    """The note with its line endings folded, since it is committed CRLF like `LICENSE`."""
    return NOTICE.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _recorded() -> dict[str, bool]:
    """Every URL an `http` record holds, mapped to whether it kept page content."""
    cassettes = sorted(CASSETTE_DIR.glob("*.jsonl"))
    assert cassettes, f"no cassettes under {CASSETTE_DIR}; this guard is reading nothing"
    found: dict[str, bool] = {}
    for path in cassettes:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
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
    text = _notice()
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


def test_the_cassettes_still_hold_both_a_kept_page_and_a_404():
    """The classification, asserted as a property rather than trusted to the test above.

    Dict equality already compares it, but only while both classes are present: if every
    record were a page, the mapping would be all-`True` on both sides and a note that had
    silently moved a URL between its lists would still read green. This says the corpus
    still has one of each, so that comparison is doing work.

    Named for the corpus and not for the note, because the corpus is what it reads. The
    first edition was called *"and it tells the pages it kept from the ones that answered
    404"*, which is `_listed`'s `REFUSED_MARKER` assertion doing the telling, one function
    over — a name promising a property its own body does not hold.
    """
    recorded = _recorded()
    kept = [url for url, page in recorded.items() if page]
    refused = [url for url, page in recorded.items() if not page]
    assert kept and refused, (
        f"the cassettes must hold both a kept page and a 404 for the note's two lists to "
        f"mean anything; got {len(kept)} kept, {len(refused)} refused"
    )


def test_the_note_attributes_each_url_to_the_publisher_and_board_it_came_from():
    """The two columns the URL comparison never reads.

    What a reader takes away from a NOTICE is the publisher's name, and every other guard
    in this file passes with `Reddit  Greenhouse` rewritten to `Allegro  SmartRecruiters`
    on the Reddit URL — a misattribution in the one file whose whole job is attribution.
    Both columns are derivable from the URL, so neither is trusted: the board must be the
    one serving the host, and the publisher must be the account the path names.
    """
    text = _notice()
    rows = re.findall(r"^ +(\S.*?) {2,}(\S+) +(https://\S+)$", text, re.M)
    urls = re.findall(r"https://\S+", text)
    # Every listed URL must have parsed into three columns. Without this a row whose
    # spacing drifts drops out of `rows`, is attributed to nothing, and says so nowhere.
    assert len(rows) == len(urls), f"{len(rows)} of {len(urls)} listed URLs carry two columns"
    assert rows, "NOTICE lists nothing"

    wrong = []
    for publisher, board, url in rows:
        split = urlsplit(url)
        account = split.path.strip("/").split("/")[0]
        if BOARD_BY_HOST.get(split.netloc) != board:
            wrong.append(f"{url}: served by {split.netloc}, attributed to {board}")
        if publisher.lower().replace(" ", "") != account.lower():
            wrong.append(f"{url}: account {account!r}, attributed to {publisher!r}")
    assert wrong == []


def test_the_note_says_what_it_carves_out_and_from_which_grant():
    """The claim itself, which the URL lists do not make.

    A NOTICE reduced to two lists of links would pass everything above it and grant
    nothing. These are the three names the carve-out is written in terms of, so deleting
    the sentence that does the work fails here rather than reading as a formatting change.
    """
    text = _notice()
    for phrase in ("LICENSE", "eval/cassettes/", "docs/decisions/0004"):
        assert phrase in text, f"NOTICE must name {phrase}"
