"""The retrieval evaluation: the corpus it reads, the judgments under it, and the metrics.

The load-bearing thing here is not any single metric but the split. Most of this query set has no
correct answer to retrieve — a degree, a tenure, a language — and averaging a zero over those
reports the retriever as failing at something it got right. That is how a published 87 % miss rate
came to be mostly the tool behaving correctly, so the tests that matter are the ones pinning which
queries a rate is taken over.
"""

from __future__ import annotations

import pytest

from apply_scout.retrieval import metrics, report
from apply_scout.retrieval.corpus import load_corpus, load_queries
from apply_scout.retrieval.judgments import Judgment
from apply_scout.retrieval.judgments import load as load_judgments
from apply_scout.retrieval.metrics import Scored
from apply_scout.retrieval.retrievers import RANKED, RETRIEVERS, bm25, substring


@pytest.fixture(scope="module")
def corpus():
    return load_corpus()


@pytest.fixture(scope="module")
def queries():
    return load_queries()


@pytest.fixture(scope="module")
def judgments():
    return load_judgments()


# --- the ground truth is complete and reachable -------------------------------------------------


def test_every_query_has_a_judgment(queries, judgments):
    assert [q.text for q in queries if q.text not in judgments] == []


def test_every_judged_repository_exists_in_the_corpus(corpus, judgments):
    """A judgment naming a repository the corpus lacks is unreachable by construction: it would
    depress every retriever's recall equally, for a reason that is not about retrieval."""
    known = set(corpus.names)
    named = {name for j in judgments.values() for name in j.relevant}
    assert named <= known, sorted(named - known)


def test_an_unanswerable_query_never_carries_relevant_repositories(judgments):
    """The two flags cannot disagree: nothing can prove a requirement nothing can prove."""
    assert [j.id for j in judgments.values() if not j.answerable and j.relevant] == []


def test_the_published_miss_count_still_reproduces(corpus, queries):
    """The README's 63 of 72. If the cassette or the corpus loader drifts, everything downstream
    is measuring a different corpus than the number it is being compared against."""
    misses = sum(1 for q in queries if not substring(q.text, corpus))
    assert (misses, len(queries)) == (63, 72)


# --- the split the whole table rests on ---------------------------------------------------------


def test_the_three_classes_account_for_every_query(queries, judgments):
    per_query = [judgments[q.text] for q in queries]
    proved = [j for j in per_query if j.has_proof]
    absent = [j for j in per_query if j.answerable and not j.has_proof]
    unanswerable = [j for j in per_query if not j.answerable]
    assert len(proved) + len(absent) + len(unanswerable) == len(queries)


def test_two_postings_asking_the_same_thing_are_two_probes(queries, judgments):
    """`SQL` appears in two postings. Judgments are keyed by text, so a count taken over the
    judgment dict loses one — the report counts per query for exactly this reason."""
    assert len(queries) > len(judgments)


def _judgment(*, relevant: tuple[str, ...], answerable: bool = True) -> Judgment:
    return Judgment(
        id="x#1", posting="p", query="q", answerable=answerable,
        relevant=frozenset(relevant), note="",
    )


def test_a_rate_over_no_data_is_none_rather_than_perfect():
    """The discipline milestone 13 forced on every other metric in this project."""
    only_unanswerable = [Scored(judgment=_judgment(relevant=(), answerable=False), ranking=())]
    assert metrics.recall_at(only_unanswerable, 1) is None
    assert metrics.mrr(only_unanswerable) is None
    assert metrics.ndcg_at(only_unanswerable, 3) is None
    assert metrics.found_any(only_unanswerable) is None


def test_queries_with_no_right_answer_are_scored_as_silence_not_recall():
    """The correction this whole table exists to make: returning nothing for an unanswerable
    requirement is the tool succeeding, and must not enter a recall denominator."""
    scored = [
        Scored(judgment=_judgment(relevant=(), answerable=False), ranking=()),
        Scored(judgment=_judgment(relevant=("a/b",)), ranking=("a/b",)),
    ]
    assert metrics.recall_at(scored, 1) == 1.0  # over the one query that has an answer
    assert metrics.correct_silence(scored) == (1, 1)
    assert metrics.noise(scored) == 0


def test_noise_is_counted_when_something_comes_back_for_nothing():
    scored = [Scored(judgment=_judgment(relevant=(), answerable=True), ranking=("a/b",))]
    assert metrics.correct_silence(scored) == (0, 1)
    assert metrics.noise(scored) == 1


# --- the metrics themselves ---------------------------------------------------------------------


def test_reciprocal_rank_reads_the_first_relevant_position():
    scored = [Scored(judgment=_judgment(relevant=("a/c",)), ranking=("a/a", "a/b", "a/c"))]
    assert metrics.mrr(scored) == pytest.approx(1 / 3)
    assert metrics.recall_at(scored, 2) == 0.0
    assert metrics.recall_at(scored, 3) == 1.0
    assert metrics.found_any(scored) == 1.0


def test_ndcg_scores_a_perfect_ranking_at_one_however_many_proofs_there_are():
    scored = [Scored(judgment=_judgment(relevant=("a/a", "a/b")), ranking=("a/a", "a/b", "a/c"))]
    assert metrics.ndcg_at(scored, 3) == pytest.approx(1.0)


# --- the finding that corrects the audit --------------------------------------------------------


def test_the_portfolios_own_matcher_recovers_nothing_over_the_substring(corpus, queries, judgments):
    """`0005` § 3.1 implies wiring `matching.mentions` into the retriever is a fix waiting to be
    applied. It is not — consecutive-token containment is barely weaker than a substring — and
    this pins the claim the table makes."""
    scored = report.score_all(corpus, queries, judgments)
    assert metrics.found_any(scored["matching.mentions"]) == metrics.found_any(
        scored["substring (ships today)"]
    )


def test_bm25_finds_far_more_and_pays_for_it_in_noise(corpus, queries, judgments):
    """Both halves, because either alone is a flattering half-truth."""
    scored = report.score_all(corpus, queries, judgments)
    ships, ranked = scored["substring (ships today)"], scored["BM25"]
    assert metrics.found_any(ranked) > metrics.found_any(ships)
    assert metrics.noise(ranked) > metrics.noise(ships)


def test_only_ranking_retrievers_are_given_rank_sensitive_metrics(corpus, queries, judgments):
    """`find_evidence` returns matches in repository-list order, so its 'top 1' is decided by when
    the account created its repositories. Printing a recall@1 for it would report chronology."""
    table = report.markdown(corpus, queries, judgments)
    for name in RETRIEVERS:
        if name in RANKED:
            continue
        row = next(line for line in table.splitlines() if line.startswith(f"| `{name}`"))
        assert row.count("n/a") == 4, row


def test_the_shipped_retriever_ranks_nothing(corpus):
    """The defect in one assertion: for a query several repositories match, the order carries no
    score — it is the corpus order, unchanged."""
    matched = substring("SQL", corpus)
    assert matched == [name for name in corpus.names if name in matched]


def test_bm25_orders_by_score_rather_than_by_corpus_order(corpus):
    ranked = bm25("MLflow experiment tracking", corpus)
    assert ranked
    assert ranked != [name for name in corpus.names if name in ranked]
    assert ranked[0] == "P0w3r223/mlops-car-price"
