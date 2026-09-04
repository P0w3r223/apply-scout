"""The published retrieval table, and the decomposition of the number it replaces."""

from __future__ import annotations

from apply_scout.retrieval import metrics
from apply_scout.retrieval.corpus import Corpus, Query
from apply_scout.retrieval.judgments import Judgment
from apply_scout.retrieval.metrics import Scored
from apply_scout.retrieval.retrievers import RANKED, RETRIEVERS

TOP_K = 3


def score_all(
    corpus: Corpus, queries: list[Query], judgments: dict[str, Judgment]
) -> dict[str, list[Scored]]:
    return {
        name: [
            Scored(judgment=judgments[q.text], ranking=tuple(retriever(q.text, corpus)))
            for q in queries
        ]
        for name, retriever in RETRIEVERS.items()
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _num(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _found(results: list[Scored]) -> str:
    """The found-at-all rate with the count that produced it — `30% (8/27)`.

    The rate alone is what this table used to print, and the fraction underneath it is the
    sentence the project actually makes about its retriever. Printing one without the other is how
    `8 of 27` came to live in the README and nowhere a diff could reach."""
    found, total = metrics.found_any_counts(results)
    if not total:
        return "n/a"
    return f"{_pct(metrics.found_any(results))} ({found}/{total})"


def markdown(
    corpus: Corpus, queries: list[Query], judgments: dict[str, Judgment]
) -> str:
    scored = score_all(corpus, queries, judgments)
    # Counted per query, not per judgment: two postings both ask for `SQL`, and a dict keyed by
    # query text holds one entry for them. They are two probes of the retriever and the class
    # totals have to add up to the query count.
    per_query = [judgments[q.text] for q in queries]
    proved = [j for j in per_query if j.has_proof]
    # Misses that a better retriever could actually recover: a repository proves the requirement
    # and the shipped retriever did not return it. The README's "48 of 63" counted keyword
    # collisions instead, and most of those queries have no answer to recover.
    baseline = scored["substring (ships today)"]
    recoverable = sum(1 for s_ in baseline if s_.judgment.has_proof and not s_.relevant_found)
    unanswerable = [j for j in per_query if not j.answerable]
    absent = [j for j in per_query if j.answerable and not j.has_proof]

    lines = [
        "# Retrieval — the one link in the chain that nothing scored",
        "",
        f"Corpus: **{len(corpus.repos)} repositories** and **{len(corpus.readmes)} READMEs**.",
        f"Queries: **{len(queries)} requirements** the evaluation's postings were structured into.",
        "Both are read back from the committed cassette, so this table costs nothing and needs no",
        "network — the corpus a retrieval evaluation wants has been in the recording since",
        "milestone 8.",
        "",
        "## What the published 87 % actually contained",
        "",
        "The README has long reported that **63 of 72 probes return no evidence**. That number",
        "reproduces exactly. What it does not say is that most of those probes have no answer to",
        "find:",
        "",
        "| class | queries | what the right answer is |",
        "|---|---:|---|",
        f"| a repository genuinely proves it | {len(proved)} | that repository |",
        f"| a real skill this portfolio lacks | {len(absent)} | nothing |",
        f"| nothing a repository could prove — a degree, a tenure, a language | "
        f"{len(unanswerable)} | nothing |",
        "",
        "So a rate taken over all 72 counts the tool's correct silence as failure. Scored only",
        "where retrieval is possible, the defect is smaller than published — and worse.",
        "",
        "## The retrievers",
        "",
        f"| retriever | ranks? | found at all | recall@1 | recall@{TOP_K} | MRR "
        f"| nDCG@{TOP_K} | correct silence | noise |",
        "|---|:-:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, results in scored.items():
        silent, silence_total = metrics.correct_silence(results)
        ranked = name in RANKED

        def rank_only(value: float | None, *, ranked: bool = ranked) -> str:
            """A rank-sensitive rate, or `n/a` for a retriever that returns a set."""
            return _pct(value) if ranked else "n/a"

        lines.append(
            f"| `{name}` | {'yes' if ranked else '**no**'} "
            f"| {_found(results)} "
            f"| {rank_only(metrics.recall_at(results, 1))} "
            f"| {rank_only(metrics.recall_at(results, TOP_K))} "
            f"| {_num(metrics.mrr(results)) if ranked else 'n/a'} "
            f"| {_num(metrics.ndcg_at(results, TOP_K)) if ranked else 'n/a'} "
            f"| {silent}/{silence_total} | {metrics.noise(results)} |"
        )

    lines += [
        "",
        f"Recall, MRR and nDCG are over the **{len(proved)} queries a repository actually",
        "proves**;",
        "correct silence is over the other "
        f"{len(absent) + len(unanswerable)}, where returning nothing is right. Both are printed",
        "because neither is honest alone: a retriever that returns everything wins the first and",
        "loses the second, and one that returns nothing does the reverse.",
        "",
        "**MRR and nDCG read `n/a` for the two unranked retrievers, and that is the headline.**",
        "`find_evidence` returns everything that matched in repository-list order. There is no",
        "score and no top-*k*, so there is no rank for a rank-sensitive metric to read — the",
        "position of a relevant repository in that list is an accident of when the account created",
        "it. This is the defect: not the matcher, the **absence of ranking**.",
        "",
        "## What this corrects",
        "",
        "`0005` § 3.1 lists three defects in this retriever and implies the third is a fix waiting",
        "to be applied: *the portfolio's better matcher is not wired to it*. The table says",
        "otherwise — **`matching.mentions` recovers nothing over the substring it would replace.**",
        "It requires the query's tokens to appear consecutively, which is barely weaker than a",
        "literal substring, so wiring it in would have changed a rounding error's worth of",
        "outcomes. The audit predicted the wrong repair.",
        "",
        "The README's other figure moves too. It reports that **48 of the 63 misses contain a",
        "distinctive keyword present in some README**, offered as an upper bound on what better",
        "probing could recover. Against the judgments the recoverable misses number "
        f"**{recoverable}**:",
        "the rest are queries no repository can answer, or skills this portfolio does not have.",
        "Most of those keyword hits were collisions on words like `field`, `system` and",
        "`production`. The original 48 is not reproducible — no committed code produced it — and",
        f"this module is the re-runnable replacement. BM25 recovers all {len(proved)}.",
        "",
        "## What this table does not cover",
        "",
        "- **It changes nothing.** `find_evidence` is untouched: its output is hashed into every",
        "  cassette key, so ranking it costs a full paid re-record. This measures first and leaves",
        "  the repair as its own decision, now with numbers under it.",
        "- **One annotator.** The judgments are hand-made and single-sourced. The three rules that",
        "  decided every contested call are written down in `retrieval/judgments.py` so a second",
        "  annotator can disagree with something specific.",
        "- **A small set.** 72 queries over 5 postings and 13 repositories. Every rate above is",
        "  printed with its denominator for that reason.",
        "- **One extraction.** These are `claude-haiku-4-5`'s requirements, the set the published",
        "  87 % was computed over. Opus extracted longer, more sentence-like requirements and the",
        "  substring retriever does *worse* on them — 46 of 50 return nothing.",
        "",
    ]
    return "\n".join(lines)
