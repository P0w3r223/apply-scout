"""The retrieval corpus and query set, read out of the committed cassette.

Nothing here is new data. The eight evaluation postings were structured into requirements and the
candidate's repositories and READMEs were fetched, both recorded, both committed — so the corpus a
retrieval evaluation needs has been sitting in `eval/cassettes/eval.jsonl` since milestone 8. This
module only reads it back, which is why the whole measurement costs nothing and needs no network.

**Queries are grouped by the model that produced them.** Two models structured the same postings
into different requirement lists, so pooling them would count one posting twice and call the result
a larger sample. `claude-haiku-4-5` is the set the README's published figure was computed over.
"""

from __future__ import annotations

import base64
import json
from collections import defaultdict
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from apply_scout.github import ReadmeDoc, Repo

#: The recording every published number in this project is replayed from.
CASSETTE = Path("eval/cassettes/eval.jsonl")
#: The model whose extractions the README's 63-of-72 was measured over.
PUBLISHED_MODEL = "claude-haiku-4-5"


# Not `slots=True`: the derived views below are `cached_property`, which stores its result in the
# instance `__dict__`. Frozen is fine — that write bypasses `__setattr__` — but slots removes the
# dict it writes into.
# `eq=False` gives identity equality and an identity hash, which is what makes this usable as a
# cache key: the generated __hash__ would hash a list and a dict, and neither is hashable.
@dataclass(frozen=True, eq=False)
class Corpus:
    """What the retriever searches, exactly as `github_evidence` was handed it.

    The derived views are computed once per corpus rather than per query. That is not premature:
    the first version tokenised all thirteen READMEs inside every BM25 call, which is 72 times over
    for one table — fast enough locally to look fine and slow enough on a CI runner to turn a
    thirty-second job into five and a half minutes."""

    repos: list[Repo]
    readmes: dict[str, ReadmeDoc]

    @property
    def names(self) -> list[str]:
        return [repo.full_name for repo in self.repos]

    @cached_property
    def documents(self) -> dict[str, str]:
        """Everything a retriever may read about each repository: metadata plus README.

        The same fields `find_evidence` looks at, so no retriever in the comparison is handicapped
        by being given less of the document than the tool it stands for."""
        documents = {}
        for repo in self.repos:
            readme = self.readmes.get(repo.full_name)
            parts = [repo.name, repo.description or "", repo.language or "", " ".join(repo.topics)]
            if readme is not None:
                parts.append(readme.text)
            documents[repo.full_name] = " ".join(parts)
        return documents

    @cached_property
    def lowered(self) -> dict[str, str]:
        return {name: text.lower() for name, text in self.documents.items()}

    @cached_property
    def tokenised(self) -> dict[str, list[str]]:
        from apply_scout.matching import tokens

        return {name: tokens(text) for name, text in self.documents.items()}


@dataclass(frozen=True, slots=True)
class Query:
    """One requirement, and the posting it was extracted from."""

    text: str
    posting: str
    model: str


def _entries(cassette: Path) -> list[dict]:
    lines = cassette.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def load_corpus(cassette: Path = CASSETTE) -> Corpus:
    """The repositories and READMEs recorded during the evaluation."""
    repos: list[Repo] = []
    readmes: dict[str, ReadmeDoc] = {}
    for entry in _entries(cassette):
        if entry.get("kind") != "github":
            continue
        body = json.loads(entry["payload"]["body"])
        if "/repos?" in entry["label"]:
            repos = [
                Repo(
                    name=item["name"],
                    full_name=item["full_name"],
                    description=item.get("description"),
                    language=item.get("language"),
                    topics=tuple(item.get("topics") or ()),
                    html_url=item["html_url"],
                )
                for item in body
            ]
            continue
        full_name = entry["label"].split("/repos/", 1)[1].rsplit("/readme", 1)[0]
        readmes[full_name] = ReadmeDoc(
            text=base64.b64decode(body["content"]).decode("utf-8", "replace"),
            html_url=body["html_url"],
        )
    return Corpus(repos=repos, readmes=readmes)


def load_queries(cassette: Path = CASSETTE, model: str = PUBLISHED_MODEL) -> list[Query]:
    """Every requirement one model extracted from the recorded postings, in recorded order.

    Deduplicated on (posting, requirement): a posting the loop re-fetched was structured twice,
    and counting the same requirement twice would weight that posting double for no reason
    beyond a retry."""
    queries: list[Query] = []
    seen: set[tuple[str, str]] = set()
    for entry in _entries(cassette):
        if entry.get("kind") != "structure":
            continue
        if not entry["label"].startswith(model):
            continue
        try:
            obj = json.loads(entry["payload"]["text"])
        except (json.JSONDecodeError, KeyError):
            continue
        if "requirements" not in obj:
            continue  # a CV, not a posting
        posting = obj.get("url") or obj.get("title") or "unknown"
        for requirement in obj["requirements"]:
            key = (posting, requirement["text"])
            if key in seen:
                continue
            seen.add(key)
            queries.append(Query(text=requirement["text"], posting=posting, model=model))
    return queries


def by_posting(queries: list[Query]) -> dict[str, list[Query]]:
    grouped: dict[str, list[Query]] = defaultdict(list)
    for query in queries:
        grouped[query.posting].append(query)
    return dict(grouped)


__all__ = [
    "CASSETTE",
    "PUBLISHED_MODEL",
    "Corpus",
    "Query",
    "by_posting",
    "load_corpus",
    "load_queries",
]
