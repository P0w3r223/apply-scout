"""The README, held to the artifacts CI already regenerates.

Nothing read `README.md` as a file before this one. CI regenerates four tables and diffs
each against `eval/expected/*.md`, and the README carries a **hand-copied second edition**
of the same numbers with nothing comparing the two. The failure mode is not hypothetical:
a metric change reddens CI until `expected/` is updated, and at that moment the README
goes stale silently — the artifact and its copy are one `diff` apart and nobody was taking
the step. They agree today, and this file is what keeps that a fact rather than a habit.

Read the artifact, not a copy of it. A guard carrying its own table would prove the README
matches *that* table, which is not the claim the README makes to a reader.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from apply_scout.cli import _build_parser

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
EXPECTED = ROOT / "eval" / "expected"
#: Which artifact each row of the README's results table was copied from. The README
#: prepends a `Runner` column the artifacts do not have; this is that column's meaning.
ARTIFACT_BY_RUNNER = {"pipeline": "pipeline.md", "agent loop": "agent.md"}


def _text(path: Path) -> str:
    """A file with its line endings folded.

    `README.md` is committed CRLF and `eval/expected/*.md` are pinned LF by
    `.gitattributes`, so a comparison of raw bytes compares line endings and not content.
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
    paragraph. A maximal run of pipe-leading lines has no such guess in it.
    """
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("|"):
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

    recorded: dict[tuple[str, str], list[str]] = {}
    for name in sorted(set(ARTIFACT_BY_RUNNER.values())):
        artifact = _table_headed(_text(EXPECTED / name), "Model")
        assert artifact[0] == header[1:], (
            f"{name} and the README disagree about the columns themselves: "
            f"{artifact[0]} vs {header[1:]}"
        )
        for row in artifact[1:]:
            recorded[(name, row[0])] = row

    assert published == recorded


def test_the_attack_rows_say_what_the_approved_table_says():
    """The four legs and the control, by verdict rather than by wording.

    Deliberately weaker than a string comparison, and the reason is written here so the
    next reader does not take it for an oversight: the artifact prints `succeeded every
    time` and the README prints `succeeded every time it reached the reader`, which is the
    same verdict carrying the qualifier the README spends a paragraph on. What must not
    drift is which legs held, so that is what this compares — and an outcome matching
    neither pattern fails rather than being quietly filed as a hold.
    """

    def verdicts(table: list[list[str]], leg: int, outcome: int) -> list[tuple[str, bool]]:
        read = []
        for row in table[1:]:
            text = row[outcome]
            held = "never succeeded" in text
            assert held != text.startswith("succeeded every time"), (
                f"outcome {text!r} is neither a hold nor a landed attack"
            )
            read.append((row[leg], held))
        return sorted(read)

    approved = _text(EXPECTED / "attack.md")
    arms = [one for one in _tables(approved) if one and one[0][0] == "payload"]
    assert len(arms) == 2, f"attack.md must print both arms, found {len(arms)}"
    # The README states one outcome column for both arms. That is only true while the arms
    # agree, and when they stop agreeing the README is wrong before any copy has drifted.
    first, second = (verdicts(one, 1, 2) for one in arms)
    assert first == second, "the arms disagree, so the README's `both arms` column is false"

    readme = _table_headed(_text(README), "what the attacker asked for")
    assert verdicts(readme, 1, 2) == first


def test_the_readme_quotes_the_retrieval_miss_rate_its_artifact_computes():
    """`63 of 72`, re-derived from the one table in `retrieval.md` that is computed.

    Not compared against that file's own `63 of 72` sentence, which is a string literal in
    `retrieval/report.py`: two hand-typed copies agreeing proves only that someone typed
    the same thing twice. The retrievers table is generated from the judgments, so this
    reddens when the judgment set moves — which is the whole point of quoting a figure.
    """
    rows = _table_headed(_text(EXPECTED / "retrieval.md"), "retriever")
    shipped = [one for one in rows[1:] if one[0].startswith("substring")]
    assert len(shipped) == 1, "retrieval.md must print exactly one row for the shipped retriever"
    row = shipped[0]

    found = re.fullmatch(r"\d+% \((\d+)/(\d+)\)", row[2])
    silence = re.fullmatch(r"(\d+)/(\d+)", row[-2])
    assert found and silence, f"unreadable row: {row}"
    hits, answerable = int(found[1]), int(found[2])
    silent, unanswerable = int(silence[1]), int(silence[2])

    misses = (answerable - hits) + silent
    total = answerable + unanswerable

    quoted = re.search(r"\*\*(\d+) of (\d+) probes return no evidence\*\*", _text(README))
    assert quoted, "the README must state the miss rate, or this guard checks nothing"
    assert (int(quoted[1]), int(quoted[2])) == (misses, total)


def _named(flag: str, text: str) -> bool:
    """Not `flag in text`: the whole value of the guard below is the flag nobody has
    written yet, and `--model` reads as documented because `--models` is. The first sweep
    behind this file reported two missing flags for exactly that reason, and three is the
    answer."""
    return re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", text) is not None


def test_every_flag_the_parser_accepts_is_named_somewhere_a_reader_looks():
    """`run --model`, `--max-steps` and `--max-cost` were accepted and documented nowhere.

    Read off the parser rather than listed here, so a flag added later arrives with this
    guard already pointing at it.

    **The fenced blocks are searched too, and its twin in `auth-log-scan` strips them.**
    That is a real disagreement and not a copy that drifted. There, every `-m` in the file
    is inside a fence — `python -m venv` — so an example proves nothing and the prose has
    an `Options:` section to answer from. Here the runnable examples *are* how `--url`,
    `--cv` and `--github-user` are taught, and there is no options section to move them to.
    Stripping fences would redden this on six flags and demand a section this README does
    not have, which is a redesign wearing a guard's clothes.
    """
    scope = [README, ROOT / "CLAUDE.md", *sorted((ROOT / "docs").glob("*.md")), *sorted(
        (ROOT / "docs" / "decisions").glob("*.md")
    )]
    text = "\n".join(_text(one) for one in scope)

    options: list[list[str]] = []
    stack = [_build_parser()]
    while stack:
        parser = stack.pop()
        for action in parser._actions:
            # By type and not by `choices`, which `--runner` also has as a plain tuple of
            # strings. The first edition asked whether every choice looked like a parser
            # and died on that tuple — loudly, which is the only reason it is not still
            # walking one subcommand deep and calling that every flag.
            if isinstance(action, argparse._SubParsersAction):
                stack.extend(action.choices.values())
            if action.option_strings and "--help" not in action.option_strings:
                options.append(action.option_strings)

    assert options, "the parser must expose options for this guard to mean anything"
    assert any(one.startswith("--") for strings in options for one in strings)
    missing = ["/".join(one) for one in options if not all(_named(flag, text) for flag in one)]
    assert missing == []
