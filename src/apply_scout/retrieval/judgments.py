"""The relevance judgments: which repository proves which requirement.

Hand-annotated over the recorded corpus and committed, because a retrieval metric is only as good
as the ground truth under it, and a judgment set nobody can inspect is not evidence. Three rules
decided every contested call, and they live here rather than in a commit message because the next
annotator needs them:

* **Named in the README, not merely used.** The corpus *is* the READMEs, so a skill argued nowhere
  in them is a skill no reader of them could find. Judging otherwise would score the annotator's
  knowledge of the code against a retriever that never sees it, and penalise every retriever for a
  miss none of them could avoid.
* **Full coverage, not a near neighbour.** A requirement naming PostgreSQL is not proved by DuckDB,
  and one naming statsmodels/PyMC/Stan is not proved by a hand-rolled bootstrap. Near misses land
  in "nothing here proves it", which is itself a finding worth reporting.
* **Building, not consuming.** Serving a FastAPI endpoint proves *REST APIs*; importing `httpx` to
  call somebody else's does not.

**Not every query has an answer, and that is the point.** A requirement asking for a degree, for
years of experience, or for a language is not something a repository can prove — the correct
retrieval for it is *nothing*. Scoring recall over those queries measures the posting's prose
rather than the retriever, which is how a published 87 % miss rate came to be mostly cases of the
tool behaving correctly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

JUDGMENTS = Path("eval/retrieval/judgments.json")


@dataclass(frozen=True, slots=True)
class Judgment:
    id: str
    posting: str
    query: str
    #: Whether *any* repository could prove this requirement. False for a degree, a tenure, a soft
    #: skill or a language — for which returning nothing is the right answer, not a miss.
    answerable: bool
    #: The repositories that do prove it. Empty is meaningful twice over: unanswerable, or
    #: answerable and genuinely absent from this portfolio.
    relevant: frozenset[str]
    note: str

    @property
    def has_proof(self) -> bool:
        return bool(self.relevant)


def load(path: Path = JUDGMENTS) -> dict[str, Judgment]:
    """Judgments keyed by query text, which is how a retriever's result is matched back."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        item["query"]: Judgment(
            id=item["id"],
            posting=item["posting"],
            query=item["query"],
            answerable=item["answerable"],
            relevant=frozenset(item["relevant"]),
            note=item["note"],
        )
        for item in raw["judgments"]
    }
