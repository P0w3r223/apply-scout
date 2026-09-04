# ADR-0012: The page quotes the artifacts; it never retypes them

Date: 2026-09-04
Status: accepted
Author: Piotr Cząstkiewicz + Claude
Related to: [ADR-0011](0011_scoring_the_retriever.md), [ADR-0004](0004_record_replay_cassettes.md)

---

## Context

The published page had drifted a full session behind the repository. It opened with the repository
name, its Limitations list named four things where the README named twenty-odd, and neither the
retrieval evaluation nor the attack suite appeared on it at all — so the two measurements that most
distinguish this project were invisible to anyone who followed the link.

Being stale was the smaller problem. Read against the committed artifacts, the page carried three
defects of a different kind:

- **It named the wrong cause.** Its limitation read *"GitHub evidence is drawn from repository
  metadata and README text, not full code search"*, while `eval/expected/retrieval.md`, committed in
  the same repository, says the loss is the **absence of ranking**. The page diagnosed the corpus;
  the measurement blames the matcher.
- **It contradicted itself inside one card.** The same two cells, `$0.0592` and `$0.1910`, were
  called *"a third of the price"* and, eleven lines later, *"roughly half the strong model's
  price"*. Both derived from correct cells. Neither was wrong about the cells; they were wrong
  about each other, and nothing could tell.
- **It printed figures no committed file contained.** A whole prompt-caching paragraph
  (`$0.3994`, `$0.2950`, `16 %`, `36 %`, a 38-turn loop), a run duration, a probe count, and the
  cost of recording the cassette. `eval/results/` is gitignored, so these had outlived the runs that
  produced them with nothing able to notice.

The common cause is not carelessness. It is that **the page was the only surface in this project
allowed to author a number.** Every table under `eval/expected/` is generated and CI diffs it; the
page was typed by hand, and a hand-typed number has no upstream to go stale against.

## Decision

**A number may appear on `docs/index.html` only if a committed artifact prints it verbatim** — a
table under `eval/expected/`, or the recorded demo cast's closing status line.

Three consequences, and they are the whole rule:

1. **To publish a new number, extend the generator that prints it.** Never the page. The generator's
   output is diffed by CI, so the new number arrives with a regression test attached.
2. **Ratios and comparisons are arguments, not cells.** *"A third of the price"* is a claim about two
   cells rather than a reading of one, and it is exactly the shape that contradicted itself here.
   The page may print both figures side by side; the argument about them belongs in the README,
   where prose is expected to argue and a reader has already spent more than a minute.
3. **A test enforces it, over the whole page rather than per claim.** `test_docs_page.py` renders the
   page to text, tokenises it, and requires every numeric token to be one an artifact prints.

## Why a class check rather than assertions per number

Both were written; only the first would have caught what actually happened.

Per-claim assertions cover the numbers somebody remembered to assert. The caching paragraph was not
a claim anyone would have thought to pin — it was a supporting detail, and it was the part with no
source at all. A rule that reads the whole rendered page has no such blind spot, and it is the shape
this repository already prefers: ADR-0011 scored a class of query rather than the one that was
complained about, and the portfolio's `created_by` check asserts a declared range rather than the
one file that fell outside it.

Two details make the class check honest rather than merely broad:

- **Whole tokens on both sides, never substrings.** A substring rule sources `75` out of `0.75 (4)`
  in `pipeline.md` — and `75` is precisely the stale completion rate that stood on this page for
  twelve days, which a neighbouring test exists to catch. The convenient version of the new check
  would have re-opened the hole the old one closes.
- **The recording is not a source; its closing status line is.** The cast carries a timestamp, a
  step counter and a per-call price in most of its frames. Treated as a whole it laundered `38` —
  the step counter — as though a table had printed it, and `38` was load-bearing in the caching
  sentence.

Exemptions are **shapes with a reason**, not a list of allowed values: `HTTP \d{3}` (a protocol
constant) and `recorded \d{4}-\d{2}-\d{2}` (when the evaluation ran). Each is cut out of the text
before tokenising, so exempting the footer's date does not also exempt a `21` claimed in a
paragraph, and a further test fails if either shape leaves the page — a dead exemption cannot sit
there quietly widening the rule.

## The grid size is not a reach count

`attack/report.py` refuses to put reach counts in the file CI diffs: how many attempts reach the
reader is a property of the installed trafilatura and libxml2, and freezing it would turn somebody's
dependency bump into a red build. This decision adds a count to that same file —
`5 payloads × 4 placements × 2 extractors = 40 attempts` — and it is **not** a reversal.

How many attempts *reach* is measured. How many are *made* is declared: it is the shape of the grid
this suite builds, identical on every machine. The distinction is written into both docstrings
because a later reader meeting a count in a file whose docstring forbids counts will otherwise read
it as precedent for adding the other kind.

## Consequences

**What it costs.** Publishing a figure is no longer free: it means a generator change and a
regenerated artifact in the same pull request. That is the intended friction — it is the difference
between the page asserting something and the page reporting something.

**What it removes.** The page lost roughly as much prose as it gained. The commentary that used to
sit on it — what each evaluation column caught, what re-recording moved — now lives one link away in
the README. A reader with sixty seconds did not reach the eleventh explanatory paragraph anyway.

**What it does not cover.** The rule is about numbers. A page can still be stale in prose, name the
wrong cause in words, or omit a card entirely, and no test here will notice — the corrected
limitation in this pass was found by reading, not by a check. Whether the page should be generated
outright, as five sibling projects in this portfolio already do, is deliberately left open: the
portfolio's page design spec is being written, and freezing a structure weeks before it is rewritten
would buy the wrong thing. The trigger to revisit is that spec landing.
