"""The retrievers under comparison. Each ranks the corpus for one requirement.

`substring` is what ships: `github_evidence.find_evidence`'s rule in ranking clothes, so the
published baseline is the production behaviour rather than a reimplementation that might flatter or
libel it.

`mentions_matcher` exists to answer a question the audit got wrong. `0005` § 3.1 lists "the
portfolio's better matcher is not wired to the retriever" among the retriever's three defects,
which reads as a fix waiting to be applied. It is not one — `matching.mentions` requires the
query's tokens to appear consecutively, which is barely weaker than a substring — and it is in this
table so the numbers say so instead of an argument.

**Every retriever here returns a ranking, which the shipped tool does not.** `find_evidence`
returns everything that matched, in repository-list order. That absence is why no recall@k or MRR
could be computed over it before, and it is the finding the comparison exists to expose.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable

from apply_scout.matching import mentions, tokens
from apply_scout.retrieval.corpus import Corpus

#: Words that carry no evidence about a skill. A requirement is mostly these, which is precisely
#: why whole-string matching fails: the distinctive part is a small minority of the sentence.
_STOPWORD_TEXT = """
    and or the a an of in for with to on at as is are be been being by from into over experience
    using use used strong good solid deep knowledge understanding familiarity ability years year
    plus nice have has must should will work working able comfortable proven track record team
    teams building build built development developer engineer engineering skills skill such
    including etc our you your we
"""
STOPWORDS = frozenset(_STOPWORD_TEXT.split())

Retriever = Callable[[str, Corpus], list[str]]


def _content(corpus: Corpus, full_name: str) -> str:
    """Everything a retriever may read about one repository: metadata plus README.

    The same fields `find_evidence` looks at, so the baseline row is not handicapped by being
    given less of the document than the tool it stands for."""
    repo = next(r for r in corpus.repos if r.full_name == full_name)
    readme = corpus.readmes.get(full_name)
    parts = [repo.name, repo.description or "", repo.language or "", " ".join(repo.topics)]
    if readme is not None:
        parts.append(readme.text)
    return " ".join(parts)


def _terms(query: str) -> list[str]:
    return [t for t in tokens(query) if t not in STOPWORDS and len(t) > 2]


def substring(query: str, corpus: Corpus) -> list[str]:
    """What ships today: the whole requirement as one literal substring.

    Returned in repository-list order, because that is what `find_evidence` does. The order is not
    a ranking and the metrics must not read it as one — which is exactly why MRR is meaningless
    for this row and is reported as such."""
    needle = query.strip().lower()
    return [name for name in corpus.names if needle in _content(corpus, name).lower()]


def mentions_matcher(query: str, corpus: Corpus) -> list[str]:
    """`matching.mentions`: consecutive-token containment, also unranked."""
    return [name for name in corpus.names if mentions(_content(corpus, name), query)]


def _idf(corpus: Corpus) -> dict[str, float]:
    total = len(corpus.names)
    seen: Counter[str] = Counter()
    for name in corpus.names:
        for term in set(tokens(_content(corpus, name))):
            seen[term] += 1
    return {t: math.log((total - c + 0.5) / (c + 0.5) + 1.0) for t, c in seen.items()}


def bm25(query: str, corpus: Corpus, *, k1: float = 1.5, b: float = 0.75) -> list[str]:
    """Term-level scoring with length normalisation — the first retriever here that *ranks*.

    Ordinary BM25 with its usual constants, deliberately: the claim is that the shipped retriever
    is missing a standard technique, not that it is missing a clever one. A tuned variant would
    make the comparison about the tuning."""
    idf = _idf(corpus)
    docs = {name: tokens(_content(corpus, name)) for name in corpus.names}
    average = sum(len(d) for d in docs.values()) / max(len(docs), 1)
    want = _terms(query)
    scored: list[tuple[float, str]] = []
    for name, doc in docs.items():
        counts = Counter(doc)
        score = 0.0
        for term in want:
            frequency = counts.get(term, 0)
            if not frequency:
                continue
            norm = frequency * (k1 + 1) / (
                frequency + k1 * (1 - b + b * len(doc) / average)
            )
            score += idf.get(term, 0.0) * norm
        if score > 0:
            scored.append((score, name))
    # Ties broken by name so the table is reproducible rather than dict-order dependent.
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [name for _, name in scored]


#: Ordered as the table prints them: what ships, the predicted fix, and a standard baseline.
RETRIEVERS: dict[str, Retriever] = {
    "substring (ships today)": substring,
    "matching.mentions": mentions_matcher,
    "BM25": bm25,
}

#: Retrievers that return an order rather than a set. MRR and nDCG mean nothing for the others,
#: and are printed as `n/a` rather than computed over an accident of repository-list order.
RANKED = frozenset({"BM25"})
