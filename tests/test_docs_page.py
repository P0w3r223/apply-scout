"""The published page — what carries the recording, and where every number on it came from.

Nothing else here covers `docs/index.html`, which is how the defect below survived: an
`<img>` pointing at a file that exists, served with a 200, raising no console error. The
page simply showed nothing, and only a person looking at it could tell.

The same blind spot let the page print figures nothing produced. **The page quotes; it never
retypes**: every number it prints is a verbatim cell of a committed artifact under
`eval/expected/`, or of the recorded run's closing status line. Two published defects are why
that rule exists, and each has a test below named after it — a paragraph of caching figures no
committed file contained, and the same two cost cells called "a third of the price" eleven
lines above "roughly half the strong model's price". Both survived review because nothing
compared the page against an artifact.

Every expected value here is read out of `eval/expected/` or `docs/demo-cast.json` rather than
pinned in this file, so a re-recording moves the assertion instead of merely reddening it.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
EXPECTED = ROOT / "eval" / "expected"
CAST = json.loads((ROOT / "docs" / "demo-cast.json").read_text(encoding="utf-8"))


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


# --------------------------------------------------------------------------------------
# The page as a reader sees it
# --------------------------------------------------------------------------------------


def _flat(text: str) -> str:
    return " ".join(text.split())


class _Rendered(HTMLParser):
    """The page's text nodes, and the structures a reader sees them in.

    Markup is not printed, so it is not a claim: the stylesheet's pixel values, the
    `aspect-ratio: 876 / 526` on the `<object>` and the comments explaining both are numbers
    no visitor reads. Attributes are never collected here, `<style>` is skipped, and
    `HTMLParser` drops comments on its own.
    """

    _SKIPPED = frozenset({"style", "script"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.prose: list[str] = []  # everything outside a <table>
        self.headline = ""
        self.tables: list[list[list[str]]] = []
        self.cards: dict[str, str] = {}
        self._skipped = 0
        self._depth = 0
        self._card_depth: int | None = None
        self._card: list[str] = []
        self._card_heading = ""
        self._heading: list[str] | None = None
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIPPED:
            self._skipped += 1
        elif tag == "div":
            self._depth += 1
            if self._card_depth is None and "card" in (dict(attrs).get("class") or "").split():
                self._card_depth, self._card, self._card_heading = self._depth, [], ""
        elif tag == "table":
            self._table = []
        elif tag == "tr":
            self._row = []
        elif tag in {"td", "th"}:
            self._cell = []
        elif tag in {"h1", "h2"}:
            self._heading = []

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIPPED:
            self._skipped = max(self._skipped - 1, 0)
        elif tag == "div":
            if self._card_depth == self._depth:
                self.cards[self._card_heading] = _flat("".join(self._card))
                self._card_depth = None
            self._depth -= 1
        elif tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(_flat("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None
        elif tag in {"h1", "h2"} and self._heading is not None:
            heading = _flat("".join(self._heading))
            if tag == "h1":
                self.headline = heading
            else:
                self._card_heading = heading
            self._heading = None

    def handle_data(self, data: str) -> None:
        if self._skipped:
            return
        self.text.append(data)
        for sink in (self._card, self._cell, self._heading):
            if sink is not None:
                sink.append(data)
        if self._table is None:
            self.prose.append(data)


def _render(html: str) -> _Rendered:
    page = _Rendered()
    page.feed(html)
    page.close()
    return page


RENDER = _render(PAGE)
PAGE_TEXT = _flat(" ".join(RENDER.text))
PROSE = _flat(" ".join(RENDER.prose))


# --------------------------------------------------------------------------------------
# The committed artifacts the page is allowed to quote
# --------------------------------------------------------------------------------------

NUMBER = re.compile(r"\d+(?:\.\d+)?")

#: The two shapes on the page that no table can source, each with the reason it is exempt.
#: Kept as shapes rather than as a list of allowed values: the match is cut out of the text
#: before the numbers are read, so exempting the footer's date does not also exempt a `21`
#: claimed in a paragraph.
UNSOURCEABLE = (
    (re.compile(r"\bHTTP (\d{3})\b"),
     "an HTTP status code is a protocol constant, not a measurement"),
    (re.compile(r"\brecorded (\d{4}-\d{2}-\d{2})\b"),
     "when the evaluation ran is a fact about the run, not a cell of it"),
)


def _artifact(name: str) -> str:
    return (EXPECTED / name).read_text(encoding="utf-8")


def _artifacts_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(EXPECTED.glob("*.md")))


def _status_lines(cast: dict) -> list[str]:
    """The recorded run's closing status line — `steps: N | tokens: A+B | cost: $C`."""
    return [f["text"] for f in cast["frames"] if f["text"].lstrip().startswith("status:")]


def _recorded_numbers(cast: dict) -> set[str]:
    """What the recording lets the page quote: the closing status line, and nothing else.

    The cast as a whole is not a source. It carries a timestamp for every frame and a step
    counter, a token count and a per-call price inside most of them, which together admit
    numbers no table prints: `38` is quotable off this recording only because its thirty-eighth
    step logged a line. The caption quotes the run's closing summary, so that one line is it.
    """
    return set(NUMBER.findall(" ".join(_status_lines(cast))))


def _quotable_numbers() -> set[str]:
    return set(NUMBER.findall(_artifacts_text())) | _recorded_numbers(CAST)


def _unquoted_numbers(text: str, quotable: set[str]) -> list[str]:
    """Numbers `text` prints that no committed artifact prints.

    Compared as whole tokens on both sides. A substring test passes numbers it should not:
    `75` — the completion rate the page went on claiming after its tables moved to 62% — sits
    inside `0.75 (4)` in `pipeline.md`, and `08` from the footer's date sits inside the
    recording's `$0.0838`. Both would read as sourced, and one of them was published.
    """
    for pattern, _ in UNSOURCEABLE:
        text = pattern.sub(" ", text)
    return [number for number in NUMBER.findall(text) if number not in quotable]


def test_every_number_the_page_prints_is_a_number_a_committed_artifact_prints():
    """The rule, enforced over the whole page: it quotes cells, it does not retype figures.

    What this would have caught, published: a caching paragraph printing $0.3994, $0.2950,
    $0.5195, 16%, 36% and a 38-turn loop, beside a caption claiming a run duration and a probe
    count — not one of those in any committed file, and none of them reproducible. Run against
    the page as it stood, this test names two dozen such numbers. To publish a new one, extend
    the generator that prints it and let CI diff the artifact.
    """
    unquoted = _unquoted_numbers(PAGE_TEXT, _quotable_numbers())
    assert not unquoted, (
        f"docs/index.html prints {sorted(set(unquoted))}, which no table under eval/expected/ "
        "and no line of the recorded run prints — the page may only quote a committed cell"
    )


def test_the_two_shapes_exempt_from_the_rule_are_both_still_printed():
    """An exemption nobody uses is a hole nobody is watching.

    Both entries in `UNSOURCEABLE` cut a span out of the page before its numbers are read, so
    a stale one silently widens what the rule above admits. If a shape leaves the page, delete
    its exemption with it.
    """
    for pattern, reason in UNSOURCEABLE:
        assert pattern.search(PAGE_TEXT), (
            f"nothing on the page matches /{pattern.pattern}/ any more, so the exemption for it "
            f"({reason}) now only widens what the page may print — delete it"
        )


def test_a_number_that_merely_hides_inside_a_cell_is_not_a_quotation():
    """The comparison is between tokens, and this is what stops it being relaxed to `in`.

    `0.75 (4)` is a real cell of `pipeline.md`. A substring test therefore sources `75%` —
    which is exactly the stale completion rate the page published for twelve days against its
    own table. Whole tokens on both sides is the only version of this rule that holds.
    """
    quotable = _quotable_numbers()
    assert "0.75" in quotable and "75" not in quotable
    assert "75" in _artifacts_text(), "the substring trap this pins is gone; keep the token test"
    assert _unquoted_numbers("Completion is 75% rather than 100%.", quotable) == ["75"]


def test_only_the_runs_closing_status_line_counts_as_the_recording():
    """A step's own bookkeeping is not a published figure, and a cast is nothing but steps.

    Taking the whole recording as a source would let the page quote any number a step happened
    to log — the committed cast admits `38` and `0` that way, and neither is in any table. The
    frame below is the shape of the one that admits `38`.
    """
    closing = "\nstatus: completed\nsteps: 5 | tokens: 48978+10983 | cost: $0.4368"
    cast = {
        "frames": [
            {"t": 114.344, "text": "[38] model claude-opus-4-8 | 11478+6829 tok | $0.1841"},
            {"t": 124.453, "text": closing},
        ]
    }
    assert _recorded_numbers(cast) == {"5", "48978", "10983", "0.4368"}


def test_the_recording_card_quotes_only_the_runs_closing_status_line():
    """The caption under the recording describes that run, so it may only quote that run.

    It used to add "33 evidence probes" and "125 seconds" and a $0.5195 uncached price beside
    the two figures the run actually printed. The status line is found by its shape, so a
    re-recording moves this assertion rather than reddening it.
    """
    card = "One run, as it happened"
    assert card in RENDER.cards, f"the {card!r} card is gone — the recording lost its caption"
    status = _status_lines(CAST)
    assert len(status) == 1, (
        f"the recording has {len(status)} closing status lines; docs/demo-cast.json changed "
        "shape and the caption's only source with it"
    )
    unquoted = _unquoted_numbers(RENDER.cards[card], _recorded_numbers(CAST))
    assert not unquoted, (
        f"the caption under the recording claims {sorted(set(unquoted))}, which the run's own "
        f"closing line does not print ({_flat(status[0])!r})"
    )


# --------------------------------------------------------------------------------------
# The claims, pinned to the cells they quote
# --------------------------------------------------------------------------------------


def _markdown_tables(markdown: str) -> list[list[list[str]]]:
    """Every pipe table in a committed artifact, as rows of cells, separators dropped."""
    tables: list[list[list[str]]] = []
    rows: list[list[str]] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if not all(set(cell) <= set("-: ") for cell in cells):
                rows.append(cells)
            continue
        if rows:
            tables.append(rows)
            rows = []
    if rows:
        tables.append(rows)
    return tables


def _key(cell: str) -> str:
    """A cell as the two formats agree on it: markdown emphasis and HTML tags carry no value."""
    return _flat(cell.replace("`", "").replace("*", "")).casefold()


def _table_headed(tables: list[list[list[str]]], first_column: str) -> list[list[str]]:
    matching = [table for table in tables if table and _key(table[0][0]) == first_column]
    assert len(matching) == 1, (
        f"expected exactly one table whose first column is {first_column!r}, found "
        f"{len(matching)} — the page and the artifact no longer describe the same thing"
    )
    return matching[0]


def _rows(table: list[list[str]]) -> list[dict[str, str]]:
    """A table as `{column: cell}` per row, so two of them compare by name, not by position."""
    header = [_key(cell) for cell in table[0]]
    rows = []
    for row in table[1:]:
        assert len(row) == len(header), f"a row has {len(row)} cells against {len(header)} columns"
        rows.append({name: _key(cell) for name, cell in zip(header, row, strict=True)})
    return rows


def _keyed(table: list[list[str]]) -> dict[str, dict[str, str]]:
    """The same, keyed by the first column — which has to identify the row on its own.

    A duplicate key would drop a row silently, and a dropped row is a published cell nothing
    compares: keying the evaluation table by `Runner` hid a wrong median cost from this file
    until a mutation went looking for it.
    """
    rows = _rows(table)
    keyed = {row[_key(table[0][0])]: row for row in rows}
    assert len(keyed) == len(rows), (
        f"{table[0][0]!r} does not identify a row on its own ({len(rows)} rows, "
        f"{len(keyed)} distinct) — comparing by it would skip whatever it collapsed"
    )
    return keyed


def _page_rows(first_column: str) -> list[dict[str, str]]:
    return _rows(_table_headed(RENDER.tables, first_column))


def _page_table(first_column: str) -> dict[str, dict[str, str]]:
    return _keyed(_table_headed(RENDER.tables, first_column))


def _artifact_table(name: str, first_column: str) -> dict[str, dict[str, str]]:
    return _keyed(_table_headed(_markdown_tables(_artifact(name)), first_column))


def _found_at_all() -> tuple[str, str]:
    """`(found, total)` for the retriever that ships, out of its `found at all` cell."""
    rows = _artifact_table("retrieval.md", "retriever")
    shipped = [label for label in rows if "ships today" in label]
    assert len(shipped) == 1, (
        f"retrieval.md marks {len(shipped)} retrievers as shipping today, so the page's "
        "headline no longer has one row to quote"
    )
    cell = rows[shipped[0]]["found at all"]
    counted = re.fullmatch(r"\d+% \((\d+)/(\d+)\)", cell)
    assert counted, (
        f"the shipped retriever's found-at-all cell reads {cell!r} and no longer prints the "
        "fraction the page's headline is a sentence about"
    )
    return counted.group(1), counted.group(2)


def test_the_headline_ratio_is_the_shipped_retrievers_cell_wherever_the_prose_states_it():
    """One page, one statement of the finding it leads with.

    The headline, the tile beside it and the Limitations bullet all state the same fraction,
    which is what the retrieval table prints for the retriever that ships. The check is over
    every ratio in the prose with that denominator rather than over three known sentences, so
    a fourth restatement is covered the moment someone writes it — and a re-scored retriever
    moves all of them together instead of leaving the loudest one behind. This is the shape of
    the defect that reached the public page: the same two cells, described two ways, eleven
    lines apart, with nothing comparing one to the other.
    """
    found, total = _found_at_all()
    stated = re.findall(r"(\d+)\s*(?:/|of the )\s*(\d+)", PROSE)
    over_total = [f"{numerator}/{denominator}" for numerator, denominator in stated
                  if denominator == total]
    assert over_total, (
        f"no sentence on the page states a ratio out of {total} any more — the finding the "
        "page is built to lead with is no longer in its prose"
    )
    contradicting = sorted({ratio for ratio in over_total if ratio != f"{found}/{total}"})
    assert not contradicting, (
        f"the page states {contradicting} where retrieval.md scores the shipped retriever at "
        f"{found}/{total} — two statements of one measurement is how the last one got published"
    )
    assert f"{found} of the {total}" in RENDER.headline, (
        f"the headline reads {RENDER.headline!r} and no longer states the {found}/{total} the "
        "retrieval table measures"
    )


def _only_row(name: str) -> dict[str, str]:
    rows = _artifact_table(name, "model")
    assert len(rows) == 1, f"{name} now reports {len(rows)} runs; the page assumed one"
    return next(iter(rows.values()))


def test_each_headline_tile_quotes_the_cell_it_summarises():
    """The four loudest numbers on the page, each against the artifact that produced it.

    A tile is read before anything that qualifies it, so a stale one is the most expensive
    number here to get wrong. Each is matched by its own caption, so re-ordering the strip
    does not quietly re-point an assertion at a different tile.
    """
    found, total = _found_at_all()
    loop = _only_row("agent.md")
    attempts = re.search(r"= (\d+) attempts", _artifact("attack.md"))
    assert attempts, "attack.md no longer states its own grid total, which the last tile quotes"
    expected = {
        "repositories found": f"{found}/{total}",
        "median cost": loop["median cost"],
        "produces a deliverable": loop["completed"],
        "attack attempts": attempts.group(1),
    }
    tiles = dict(re.findall(r'<li class="kpi"><b>(.*?)</b><span>(.*?)</span>', PAGE))
    assert len(tiles) == len(expected), (
        f"the page shows {len(tiles)} headline tiles and this test pins {len(expected)}"
    )
    for caption, cell in expected.items():
        printed = [value for value, text in tiles.items() if caption in text]
        assert len(printed) == 1, f"no single tile is captioned {caption!r} any more"
        assert printed[0] == cell, (
            f"the {caption!r} tile prints {printed[0]!r} where the committed table prints "
            f"{cell!r} — regenerate the page's tiles from eval/expected/"
        )


def test_the_published_retrieval_table_is_the_committed_one():
    """Cell for cell, by row and column name — a transposition is a lie a token check misses.

    Every number in this table is also a number somewhere in `retrieval.md`, so swapping
    recall@1 with recall@3, or moving BM25's row onto the retriever that ships, passes the
    page-wide rule above and would publish the opposite finding.
    """
    artifact = _artifact_table("retrieval.md", "retriever")
    for label, row in _page_table("retriever").items():
        assert label in artifact, (
            f"the page publishes a retriever {label!r} that retrieval.md does not score"
        )
        for column, printed in row.items():
            assert column in artifact[label], (
                f"the page's {label!r} row prints a column {column!r} that retrieval.md has no "
                "cell for — a column the page computes itself is not a quotation"
            )
            assert printed == artifact[label][column], (
                f"the page prints {printed!r} for {label!r}/{column!r} where retrieval.md "
                f"prints {artifact[label][column]!r}"
            )


def test_the_published_evaluation_rows_are_the_committed_cells():
    """The page merges two committed tables into one; the merge is where a cell can drift.

    `Runner` is the page's own column and it names the artifact each row must come from, so a
    row attributed to the wrong runner fails here rather than reading as a plausible result.
    Rows are compared as a list: two of the three say `pipeline`, and keying on that dropped
    one of them — with its median cost — out of this comparison entirely.
    """
    artifacts = {"pipeline": "pipeline.md", "agent loop": "agent.md"}
    aliases = {"median calls": "median llm calls"}
    published = _page_rows("runner")
    recorded = sum(len(_artifact_table(name, "model")) for name in artifacts.values())
    assert len(published) == recorded, (
        f"the page publishes {len(published)} evaluation rows where eval/expected/ reports "
        f"{recorded} runs — a run that is not on the page is a result not published"
    )
    for row in published:
        runner, model = row["runner"], row["model"]
        assert runner in artifacts, (
            f"the page publishes a runner {runner!r} that no committed table reports"
        )
        committed = _artifact_table(artifacts[runner], "model")
        assert model in committed, f"{artifacts[runner]} reports no run of {model!r}"
        for column, printed in row.items():
            if column == "runner":
                continue
            cell = committed[model].get(aliases.get(column, column))
            assert cell is not None, (
                f"the page's {runner}/{model} row prints a column {column!r} that "
                f"{artifacts[runner]} has no cell for"
            )
            assert printed == cell, (
                f"the page prints {printed!r} for {runner}/{model}/{column!r} where "
                f"{artifacts[runner]} prints {cell!r}"
            )


def _attack_arms() -> list[dict[str, str]]:
    """Each arm of the attack grid as `{payload: outcome}` — one per extractor."""
    arms = [table for table in _markdown_tables(_artifact("attack.md"))
            if table and _key(table[0][0]) == "payload"]
    assert arms, "attack.md publishes no payload table any more"
    return [{_key(row[0]): _key(row[-1]) for row in arm[1:]} for arm in arms]


def test_the_attack_table_publishes_the_verdict_both_arms_recorded():
    """Every payload's verdict, against the suite — including the ones that read as boring.

    A table of "never succeeded" is the easiest thing on this page to write by hand and the
    hardest to notice is wrong, which is why the suite calibrates itself against a removed
    guard. The page must carry what the run recorded: the same payloads, and the same
    outcomes, so a guard that closes or opens moves the page instead of leaving it boasting.
    """
    arms = _attack_arms()
    assert len({tuple(sorted(arm.items())) for arm in arms}) == 1, (
        "the two extractor arms of attack.md no longer agree, so the page's claim that both "
        "extractors read the same is no longer what the suite recorded"
    )
    published = {payload: row["outcome"] for payload, row in _page_table("payload").items()}
    assert set(published) == set(arms[0]), (
        f"the page publishes payloads {sorted(published)} where the suite ran "
        f"{sorted(arms[0])} — a payload dropped from the page is a result not published"
    )
    for payload, outcome in arms[0].items():
        assert published[payload] == outcome, (
            f"the page publishes {published[payload]!r} for {payload!r} where attack.md "
            f"records {outcome!r}"
        )


def test_the_page_names_the_leg_the_suite_leaves_open():
    """The verdict in the prose, not only in the table, and in both directions.

    The exfiltration row is the failure this project publishes rather than hides. If the suite
    ever records it as closed, the paragraph claiming an open outbound leg becomes the same
    kind of stale prose as the completion rate above — and if it stays open, the page has to
    keep saying so.
    """
    landed = sorted(payload for payload, outcome in _attack_arms()[0].items()
                    if outcome != "never succeeded")
    published_as_open = "narrowed, not closed" in PROSE
    assert published_as_open == bool(landed), (
        f"attack.md records {landed or 'no'} payload(s) still succeeding while the page "
        f"{'does not say' if landed else 'still says'} the outbound leg is open"
    )
    for payload in landed:
        assert payload in PAGE_TEXT, (
            f"the suite records {payload!r} succeeding and the page never names it"
        )


def test_the_page_quotes_the_two_costs_it_compares():
    """The pair of cells the page's only cost comparison is made of.

    Read out of the artifacts by role rather than by value — the loop's row, and the pipeline
    row for the model the loop did not run — so re-recording moves both figures in the
    sentence with them.
    """
    loop = _only_row("agent.md")
    pipeline = _artifact_table("pipeline.md", "model")
    strong = [row for model, row in pipeline.items() if model != loop["model"]]
    assert len(strong) == 1, (
        f"pipeline.md reports {len(strong)} models the loop did not run; the page's comparison "
        "assumes exactly one strong model to compare against"
    )
    compared = re.search(r"at (\$[\d.]+) against the strong model's (\$[\d.]+)", PROSE)
    assert compared, "the page no longer compares the loop's cost against the strong model's"
    assert compared.group(1) == loop["median cost"], (
        f"the page compares {compared.group(1)!r} where agent.md prints "
        f"{loop['median cost']!r} as the loop's median cost"
    )
    assert compared.group(2) == strong[0]["median cost"], (
        f"the page compares against {compared.group(2)!r} where pipeline.md prints "
        f"{strong[0]['median cost']!r} for {strong[0]['model']}"
    )


#: Ways of saying a number the page did not quote but worked out. Each of these was published
#: on this page, in prose, over cells that were themselves correct.
DERIVED = (
    r"\ba (?:third|quarter|fifth) of\b",
    r"\bhalf (?:the|of|a)\b",
    r"\btwice\b",
    r"\d+(?:\.\d+)?\s*(?:\xd7|x\b|times\b)",
    r"\b(?:two|three|four|five|six|seven|eight|nine|ten)\s+times\b",
)


def test_the_page_states_no_ratio_it_worked_out_from_two_cells():
    """A ratio is an argument about cells, not a cell, and this page is only allowed to quote.

    Two of these shipped together in one card: the same $0.0592 and $0.1910 called "a third of
    the price" and, eleven lines later, "roughly half the strong model's price". Both derived
    from correct cells, both unfalsifiable by any diff, and contradicting each other in public
    for as long as the page stood. The comparison itself is not banned — the page still prints
    both costs side by side — only the arithmetic no artifact carries. Ratios live in the
    README, where prose is expected to argue.
    """
    worked_out = sorted({match.group(0).strip() for pattern in DERIVED
                         for match in re.finditer(pattern, PROSE, re.IGNORECASE)})
    assert not worked_out, (
        f"the page works out {worked_out} from cells instead of quoting them — move the "
        "comparison to the README and print the two figures the reader can check"
    )
