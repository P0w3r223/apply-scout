"""The README, held to the artifacts CI already regenerates.

Nothing read `README.md` as a file before this one. CI regenerates four tables and diffs
each against `eval/expected/*.md`, and the README carries a **hand-copied second edition**
of the same numbers with nothing comparing the two. The failure mode is not hypothetical:
a metric change reddens CI until `expected/` is updated, and at that moment the README
goes stale silently — the artifact and its copy are one `diff` apart and nobody was taking
the step. They agree today, and this file is what keeps that a fact rather than a habit.

Read the artifact, not a copy of it. A guard carrying its own table would prove the README
matches *that* table, which is not the claim the README makes to a reader.

**Every registry below is asserted in both directions against the thing it stands for.**
The first edition pinned two artifact names, two cassettes and five attack rows by hand, and
two reviews reddened all of them by adding a file or a row the registry did not know about —
each time leaving a test green over exactly the case its own docstring promised to catch. The
second review then found the same shape *inside the fix*: a test named for "is this artifact
claimed by a guard" that compared a directory to a constant and would have passed with every
guard in the file deleted. A hand-maintained list inside a guard against hand-maintained lists
is worth naming once and never shipping again.

*This file duplicates a markdown table walker that `tests/test_docs_page.py` already has, and
the copy had drifted from the original. The divergence is repaired below; the duplication is
not, because lifting one into a shared module is its own change with its own blast radius.*
"""

from __future__ import annotations

import argparse
import functools
import re
from pathlib import Path

from apply_scout.cli import _build_parser

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
EXPECTED = ROOT / "eval" / "expected"
#: Which artifact each row of the README's results table was copied from. The README
#: prepends a `Runner` column the artifacts do not have; this is that column's meaning.
ARTIFACT_BY_RUNNER = {"pipeline": "pipeline.md", "agent loop": "agent.md"}
#: Every approved table some guard in this file answers for. Asserted against the directory
#: **and** against this file's own source, so a name cannot be registered and then read by
#: nobody — which is what the first edition of that test permitted.
GUARDED_ARTIFACTS = set(ARTIFACT_BY_RUNNER.values()) | {"attack.md", "retrieval.md"}
#: Which README sentence describes each payload `attack.md` names. The README spells out
#: what the attacker asked for and the artifact prints the payload id, so without this the
#: two tables meet only on `leg` — which is not unique, two rows being `[C] reach`, and
#: which leaves the README free to attribute an outcome to the wrong attack entirely.
DESCRIPTION_BY_PAYLOAD = {
    "read_secret": "read ~/.ssh/id_rsa via read_cv",
    "internal_fetch": "fetch 169.254.169.254 directly",
    "redirect_fetch": "fetch it behind a 302",
    "exfiltrate": "send data to an ordinary public host",
    "benign": "an ordinary sentence (control)",
}
#: Flags the documents name in order to say they do **not** exist, which the sweep below
#: cannot tell from a flag that does. Pinned in both directions: the parser may not accept
#: one, and the documents must still deny one — otherwise the entry outlives its sentence
#: and eventually fires a message pointing at prose nobody can find.
DOCUMENTED_AS_ABSENT = ("--max-tokens",)
#: How a block scopes itself to every subcommand instead of naming one. `--cassette-mode`
#: and `--cassette` are documented once, for both, and a per-subcommand reader that could
#: not see that would demand the paragraph be written twice.
EVERY_SUBCOMMAND = "both subcommands"


#: Which `eval/expected/*.md` a guard has actually opened this session. Recorded rather
#: than inferred: the artifacts are read two different ways — `attack.md` and
#: `retrieval.md` by name, `pipeline.md` and `agent.md` through `ARTIFACT_BY_RUNNER` — and
#: a source-text heuristic convicts the second, which is the better of the two patterns.
_READ_FROM_EXPECTED: set[str] = set()


def _text(path: Path) -> str:
    """A file, recorded if it is an approved artifact, with its line endings folded."""
    if path.parent == EXPECTED:
        _READ_FROM_EXPECTED.add(path.name)
    return _read(path)


@functools.cache
def _read(path: Path) -> str:
    """A file with its line endings folded.

    Every blob here is committed LF. The working tree is not: on a checkout with
    `core.autocrlf` set these arrive CRLF, so a comparison of raw bytes compares the
    checkout's line endings and not content. *An earlier edition of this docstring said
    `README.md` was committed CRLF and `eval/expected/*.md` were LF by contrast — read off a
    `grep` pattern that matched every line of whatever it was pointed at, with the figure
    equalling the line count.* The fold is load-bearing; only the reason was wrong.

    It matters beyond tidiness: a contributor who believed it might reconcile the two by
    adding `text eol=crlf`, which `.gitattributes` deliberately withholds and which would
    break the `diff -u` contract its own comment defends.
    """
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _cell(raw: str) -> str:
    """One table cell, stripped of the emphasis the README adds and the artifact does not.

    The README bolds two cells and backticks every model id. Those are presentation; the
    number is the claim, and a guard that compared them raw would report a **1.00 (4)**
    against a 1.00 (4) as a difference.
    """
    return raw.replace("**", "").replace("`", "").strip()


def _tables(text: str) -> list[list[list[str]]]:
    """Every markdown table, as rows of cells, separator rows dropped.

    Walked rather than matched by regex: a pattern for a whole table has to guess where one
    ends, and this README puts a two-column table with an empty header immediately after a
    paragraph. A maximal run of pipe-delimited lines has no such guess in it.

    Both ends are required, which `tests/test_docs_page.py`'s original does and the first
    copy of it here dropped: a prose line merely *beginning* with a pipe was swallowed into
    whatever table preceded it.
    """
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [_cell(one) for one in stripped.strip("|").split("|")]
            if not all(set(one) <= set("-: ") for one in cells):
                current.append(cells)
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return tables


def _table_headed(text: str, first: str) -> list[list[str]]:
    """The one table whose first header cell is `first`, asserted to be unique.

    Taking the first of several would leave a second table held to nothing while this file
    went on reporting green — the shape `0010` §5 names twice in two repositories.
    """
    found = [one for one in _tables(text) if one and one[0] and one[0][0] == first]
    assert len(found) == 1, f"expected exactly one table headed {first!r}, found {len(found)}"
    return found[0]


def _column(header: list[str], name: str) -> int:
    """The index of a named column, with a message when it is not there.

    `header.index(name)` raises a bare `ValueError` naming the column and nothing else,
    which is the only failure in this file that would arrive without a sentence.
    """
    assert name in header, f"the table has no {name!r} column; it reads {header}"
    return header.index(name)


def test_every_approved_artifact_is_claimed_by_a_guard_in_this_file():
    """The directory decides what must be checked — **and the registry stands for nothing
    unless a guard below actually reads the name.**

    A review added `agent-opus.md` with a full table and no README row, and every test here
    stayed green: the direction the results guard's docstring calls the one a reader never
    notices. *The fix for that stopped at a set comparison, and the next review deleted
    `test_the_attack_rows_say_what_the_approved_table_says` outright and watched this test
    stay green while going on asserting that `attack.md` is claimed by a guard in this
    file.* That is the defect this whole file was written against, displaced one hop into
    the test named for it.
    """
    names = {one.name for one in EXPECTED.glob("*.md")}
    assert names == GUARDED_ARTIFACTS

    # Run them and see what they open. Deleting a guard reddens this twice over: the call
    # below stops resolving, and the artifact it read stops being recorded. A source-text
    # heuristic was tried first and convicted `pipeline.md` and `agent.md`, which are read
    # through `ARTIFACT_BY_RUNNER` rather than by literal — punishing the better pattern.
    _READ_FROM_EXPECTED.clear()
    test_the_results_table_carries_the_numbers_its_artifacts_print()
    test_the_attack_rows_say_what_the_approved_table_says()
    test_the_readme_quotes_the_retrieval_miss_rate_its_artifact_computes()
    unread = sorted(names - _READ_FROM_EXPECTED)
    assert unread == [], f"{unread} is approved and registered, and no guard here reads it"


def test_the_results_table_carries_the_numbers_its_artifacts_print():
    """Every cell of the README's three-row table, against the two files CI diffs.

    Both directions: a README row naming no artifact fails, and an artifact row the README
    does not carry fails too. The second is the one a reader never notices — a new model in
    `pipeline.md` would leave the page silently reporting a comparison that has moved on.
    """
    readme = _table_headed(_text(README), "Runner")
    header, rows = readme[0], readme[1:]
    assert rows, "the results table must have rows for this guard to mean anything"

    published: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        runner, rest = row[0], row[1:]
        assert runner in ARTIFACT_BY_RUNNER, f"unknown runner {runner!r} in the README's table"
        published[(ARTIFACT_BY_RUNNER[runner], rest[0])] = rest
    # Both sides are dicts, so a repeated (runner, model) silently overwrites and the
    # comparison passes while the page shows a row nothing produced. A review inserted a
    # second haiku pipeline row reading 99% above the real one and this file said nothing.
    assert len(published) == len(rows), "the README's table names one (runner, model) twice"

    recorded: dict[tuple[str, str], list[str]] = {}
    for name in sorted(set(ARTIFACT_BY_RUNNER.values())):
        artifact = _table_headed(_text(EXPECTED / name), "Model")
        assert artifact[0] == header[1:], (
            f"{name} and the README disagree about the columns themselves: "
            f"{artifact[0]} vs {header[1:]}"
        )
        before = len(recorded)
        for row in artifact[1:]:
            recorded[(name, row[0])] = row
        assert len(recorded) - before == len(artifact) - 1, f"{name} names one model twice"

    assert published == recorded


def test_the_attack_rows_say_what_the_approved_table_says():
    """The four legs and the control, bound to the attack each one describes.

    The outcome is compared **by verdict rather than by wording**, deliberately: the
    artifact prints `succeeded every time` and the README prints `succeeded every time it
    reached the reader`, the same verdict carrying the qualifier the README spends a
    paragraph on. An outcome matching neither pattern fails rather than being filed as a
    hold.

    What is *not* weakened is which row each verdict belongs to. The first edition keyed on
    `leg`, which two rows share, and left the description column — the sentence a reader
    actually reads — compared to nothing: a review swapped two descriptions so the page
    claimed exfiltration was blocked, and this test stayed green.
    """

    def verdicts(table: list[list[str]], described, leg: str, outcome: str):
        header = table[0]
        leg_at, outcome_at = _column(header, leg), _column(header, outcome)
        read: dict[str, tuple[str, bool]] = {}
        for row in table[1:]:
            assert len(row) == len(header), f"row {row} does not match the header {header}"
            text = row[outcome_at]
            held = "never succeeded" in text
            assert held != text.startswith("succeeded every time"), (
                f"outcome {text!r} is neither a hold nor a landed attack"
            )
            key = described(row[0])
            assert key not in read, f"two rows describe {key!r}"
            read[key] = (row[leg_at], held)
        return read

    def by_payload(payload: str) -> str:
        assert payload in DESCRIPTION_BY_PAYLOAD, f"attack.md prints unmapped {payload!r}"
        return DESCRIPTION_BY_PAYLOAD[payload]

    approved = _text(EXPECTED / "attack.md")
    arms = [one for one in _tables(approved) if one and one[0][0] == "payload"]
    assert len(arms) == 2, f"attack.md must print both arms, found {len(arms)}"
    # The README states one outcome column for both arms. That is only true while the arms
    # agree, and when they stop agreeing the README is wrong before any copy has drifted.
    first, second = (verdicts(one, by_payload, "leg", "outcome") for one in arms)
    assert first == second, "the arms disagree, so the README's `both arms` column is false"
    assert set(first) == set(DESCRIPTION_BY_PAYLOAD.values()), (
        "the map above describes payloads attack.md no longer prints"
    )

    readme = _table_headed(_text(README), "what the attacker asked for")
    # By header text, so the README cannot quietly stop claiming both arms — the claim the
    # comment above is spending its argument on was the one cell nothing read.
    assert verdicts(readme, lambda one: one, "leg", "outcome, both arms") == first


def test_the_readme_quotes_the_retrieval_miss_rate_its_artifact_computes():
    """`63 of 72`, re-derived from the one table in `retrieval.md` that is computed.

    Not compared against that file's own `63 of 72` sentence, which is a string literal in
    `retrieval/report.py`: two hand-typed copies agreeing proves only that someone typed
    the same thing twice. The retrievers table is generated from the judgments, so this
    reddens when the judgment set moves — which is the whole point of quoting a figure.
    """
    rows = _table_headed(_text(EXPECTED / "retrieval.md"), "retriever")
    header = rows[0]
    shipped = [one for one in rows[1:] if one[0].startswith("substring")]
    assert len(shipped) == 1, "retrieval.md must print exactly one row for the shipped retriever"
    row = shipped[0]

    # By column name rather than by position: an inserted metric would otherwise move the
    # cells under a reader that still trusts its indices.
    found = re.fullmatch(r"\d+% \((\d+)/(\d+)\)", row[_column(header, "found at all")])
    silence = re.fullmatch(r"(\d+)/(\d+)", row[_column(header, "correct silence")])
    assert found and silence, f"unreadable row: {row}"
    hits, answerable = int(found[1]), int(found[2])
    silent, unanswerable = int(silence[1]), int(silence[2])

    misses = (answerable - hits) + silent
    total = answerable + unanswerable

    # Every occurrence of the claim, and exactly one. Matched without the bold markers,
    # which are presentation: the *"same ratio two different ways"* defect this portfolio
    # has published once was prose, and the first edition of this pattern required `**` and
    # so passed an unbolded second copy. It still does not catch a contradicting figure
    # written in different words — `— or 71 of 72, depending how you count` — and widening
    # it that far starts convicting ordinary prose.
    quoted = re.findall(r"(\d+) of (\d+) probes return no evidence", _text(README))
    assert len(quoted) == 1, f"the README states the miss rate {len(quoted)} times, not once"
    assert (int(quoted[0][0]), int(quoted[0][1])) == (misses, total)


def _named(flag: str, text: str) -> bool:
    """Not `flag in text`: the whole value of the guard below is the flag nobody has
    written yet, and `--model` reads as documented because `--models` is."""
    return re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", text) is not None


def _blocks(text: str) -> list[str]:
    """Documentation in blocks — each fenced block whole, each run of adjacent prose lines.

    The unit matters: a flag is documented *for a subcommand* when something naming that
    subcommand also names the flag, and the smallest honest scope for "also" is the block.
    A whole-file search cannot make that distinction, and that is not theoretical — see the
    guard below.
    """
    blocks: list[str] = []
    current: list[str] = []
    fenced = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            if current:
                blocks.append("\n".join(current))
                current = []
            fenced = not fenced
            continue
        if fenced or line.strip():
            current.append(line)
        elif current:
            blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))
    return blocks


def test_every_flag_the_parser_accepts_is_named_where_its_subcommand_is():
    """`run --model`, `--max-steps`, `--max-cost` and `--out` were undocumented.

    **Four, not the three an earlier sweep reported**, and the fourth is why this guard is
    scoped to a block instead of to the whole corpus. `--out` belongs to both subcommands
    and appeared only in `CLAUDE.md`'s `python -m apply_scout.retrieval --out` and
    `python -m apply_scout.attack --out` — two entirely different commands — so a
    whole-file search called it documented while a reader of `apply-scout run --help` had
    nowhere to read about it. A flag is documented for a subcommand when a block that names
    that subcommand also names the flag, or when the block scopes itself to every one.

    The parser is walked rather than listed here, so a flag added later arrives with this
    guard already pointing at it. Fenced blocks are searched, unlike in the `auth-log-scan`
    twin which strips them: there every `-m` in the file is inside a fence (`python -m
    venv`) so an example proves nothing, and the prose has an `Options:` section to answer
    from. Here the runnable examples *are* how `--url`, `--cv` and `--github-user` are
    taught. Block scoping is what makes searching them safe.
    """
    scope = [README, ROOT / "CLAUDE.md", *sorted((ROOT / "docs").rglob("*.md"))]
    assert len(scope) > 2, "the documentation sweep found no docs/ markdown at all"
    blocks = [one for path in scope for one in _blocks(_text(path))]
    corpus = "\n".join(blocks)

    parser = _build_parser()
    subs = [one for one in parser._actions if isinstance(one, argparse._SubParsersAction)]
    assert len(subs) == 1, "the parser's subcommand layout has changed under this guard"

    missing = []
    for name, sub in subs[0].choices.items():
        scoped = [
            one for one in blocks
            if f"apply-scout {name}" in one or EVERY_SUBCOMMAND in one.lower()
        ]
        assert scoped, f"no documentation block names `apply-scout {name}` at all"
        for action in sub._actions:
            flags = action.option_strings
            # The help action, whole: filtering the string `--help` alone leaves `-h`
            # behind and demands the documents name a flag argparse wrote itself.
            if not flags or "--help" in flags:
                continue
            # Every spelling: naming one half of a `-m/--model` pair leaves the other
            # unfindable, which is the defect in miniature.
            if not all(any(_named(flag, one) for one in scoped) for flag in flags):
                missing.append(f"{name} {'/'.join(flags)}")
    assert missing == []

    # The other direction for `DOCUMENTED_AS_ABSENT`: the parser must not accept one, and
    # the documents must still deny one. Without the second half the entry outlives the
    # sentence it stands for and eventually fires a message naming prose nobody can find.
    accepted = {one for sub in subs[0].choices.values() for a in sub._actions
                for one in a.option_strings}
    lying = sorted(accepted & set(DOCUMENTED_AS_ABSENT))
    assert not lying, f"{lying} is accepted by the parser and documented as not existing"
    stale = [one for one in DOCUMENTED_AS_ABSENT if not _named(one, corpus)]
    assert stale == [], f"{stale} is pinned as documented-absent and no document mentions it"
