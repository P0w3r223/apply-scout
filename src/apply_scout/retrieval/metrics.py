"""Retrieval metrics, scored only over the queries they can mean something for.

The discipline is the one milestone 13 forced on the rest of this harness: a metric with no data
returns `None` and prints as `n/a`, never its best value, and every mean carries the count it was
taken over. It matters more here than anywhere else in the project, because **most of this query
set has no correct answer to retrieve.** A requirement asking for a degree or for five years of
experience cannot be served by any repository; averaging a recall of 0 over those would report the
retriever as failing at something it got right.

So the queries split three ways and are scored separately:

* **answerable and proved** — some repository does prove it. Recall@k, MRR and nDCG live here, and
  this is the only subset that says how good the retriever is at retrieving.
* **answerable and absent** — a real skill this portfolio genuinely lacks. The right answer is
  nothing, and returning nothing is scored as correct silence.
* **unanswerable** — a degree, a tenure, a soft skill, a language. Also correct silence.

Reporting the last two as "misses", which is what a rate over all 72 queries does, is how a
published 87 % came to be mostly the tool behaving correctly.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from apply_scout.retrieval.judgments import Judgment


@dataclass(frozen=True, slots=True)
class Scored:
    """One retriever's result for one query, with the judgment it is scored against."""

    judgment: Judgment
    ranking: tuple[str, ...]

    @property
    def relevant_found(self) -> list[int]:
        """1-based ranks of the relevant repositories, in rank order."""
        return [
            i for i, name in enumerate(self.ranking, 1) if name in self.judgment.relevant
        ]


def recall_at(scored: Sequence[Scored], k: int) -> float | None:
    """Share of proved queries with at least one relevant repository in the top *k*."""
    subset = [s for s in scored if s.judgment.has_proof]
    if not subset:
        return None
    return sum(1 for s in subset if any(r <= k for r in s.relevant_found)) / len(subset)


def mrr(scored: Sequence[Scored]) -> float | None:
    """Mean reciprocal rank of the first relevant repository, over proved queries."""
    subset = [s for s in scored if s.judgment.has_proof]
    if not subset:
        return None
    total = 0.0
    for s in subset:
        ranks = s.relevant_found
        total += 1.0 / ranks[0] if ranks else 0.0
    return total / len(subset)


def ndcg_at(scored: Sequence[Scored], k: int) -> float | None:
    """nDCG@k with binary relevance, over proved queries.

    The ideal ranking puts every relevant repository first, so the denominator depends on how many
    a query has — a query with four proofs is not scored against a ceiling built for one."""
    subset = [s for s in scored if s.judgment.has_proof]
    if not subset:
        return None
    total = 0.0
    for s in subset:
        gain = sum(1.0 / math.log2(r + 1) for r in s.relevant_found if r <= k)
        ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(s.judgment.relevant), k) + 1))
        total += gain / ideal if ideal else 0.0
    return total / len(subset)


def correct_silence(scored: Sequence[Scored]) -> tuple[int, int]:
    """(queries answered correctly with nothing, queries where nothing was the right answer).

    Reported beside recall rather than folded into it. A retriever that returns everything would
    score well on recall and destroy this column, and one that returns nothing does the reverse —
    neither number is honest alone."""
    subset = [s for s in scored if not s.judgment.has_proof]
    return sum(1 for s in subset if not s.ranking), len(subset)


def noise(scored: Sequence[Scored]) -> int:
    """Queries that had no right answer and got one anyway."""
    return sum(1 for s in scored if not s.judgment.has_proof and s.ranking)


def found_any(scored: Sequence[Scored]) -> float | None:
    """Share of proved queries where a relevant repository appears *anywhere* in the result.

    The only recall an unranked retriever can honestly be given. `recall@k` asks whether a
    relevant repository is in the top *k*, and for a retriever that returns matches in
    repository-list order the top *k* is decided by when the account created its repositories —
    so a `recall@1` for it would report an accident of chronology as retrieval quality."""
    subset = [s for s in scored if s.judgment.has_proof]
    if not subset:
        return None
    return sum(1 for s in subset if s.relevant_found) / len(subset)
