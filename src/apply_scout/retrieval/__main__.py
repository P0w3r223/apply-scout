"""`python -m apply_scout.retrieval [--out PATH]` — score the retriever against the judgments.

Reads the corpus and the queries out of the committed cassette and the ground truth out of
`eval/retrieval/judgments.json`: no key, no network, no model call, $0. Exits non-zero when a
judgment names a repository the corpus does not contain, which is the one way this table could
quietly start measuring nothing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from apply_scout.retrieval import judgments as judgments_module
from apply_scout.retrieval import report
from apply_scout.retrieval.corpus import load_corpus, load_queries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apply-scout retrieval", description=__doc__)
    parser.add_argument("--out", type=Path, help="Write the table here instead of stdout.")
    args = parser.parse_args(argv)

    corpus = load_corpus()
    queries = load_queries()
    judgments = judgments_module.load()

    # A judgment naming a repository that is not in the corpus is unreachable by construction, so
    # it would depress every retriever's recall equally and for a reason that has nothing to do
    # with retrieval — a renamed repository silently becoming a permanent miss.
    known = set(corpus.names)
    unknown = sorted(
        {name for j in judgments.values() for name in j.relevant if name not in known}
    )
    missing = [q.text for q in queries if q.text not in judgments]
    if unknown or missing:
        for name in unknown:
            print(f"judgment names a repository not in the corpus: {name}", file=sys.stderr)
        for text in missing[:5]:
            print(f"query has no judgment: {text[:80]}", file=sys.stderr)
        return 1

    table = report.markdown(corpus, queries, judgments)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(table, encoding="utf-8", newline="\n")
    else:
        print(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
