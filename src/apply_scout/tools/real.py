"""Assemble the real toolset for an agent run.

As of milestone 3 all three tools are live (fetch posting, read CV, GitHub evidence).
Dependencies default to production wiring but can be injected — which is how the tools
are tested — and they all share the same contracts, so the agent loop is unchanged.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from apply_scout import config
from apply_scout.fetch import Extractor, Fetcher, GuardedFetcher, HttpFetcher
from apply_scout.github import DiskCache, GitHubClient
from apply_scout.structuring import AnthropicStructurer, Structurer
from apply_scout.tools.base import Tool
from apply_scout.tools.fetch_job_posting import FetchJobPosting
from apply_scout.tools.github_evidence import GithubEvidence
from apply_scout.tools.read_cv import ReadCV
from apply_scout.tools.submit_report import SubmitReport


def real_tools(
    *,
    readable: Iterable[str | Path],
    fetcher: Fetcher | None = None,
    structurer: Structurer | None = None,
    github: GitHubClient | None = None,
    extractor: Extractor | None = None,
    model: str = config.STRUCTURE_MODEL,
    submit: SubmitReport | None = None,
    fetch: FetchJobPosting | None = None,
    evidence: GithubEvidence | None = None,
) -> list[Tool]:
    """The live tools for a real run. Defaults to production wiring; inject to test.

    `submit` is the terminal tool the run finishes with. A caller that needs the submitted
    deliverable — the CLI to print it, the eval harness to score it — passes its own
    instance and reads `submit.submitted` afterwards. `fetch` and `evidence` are the same
    arrangement at the other end of the run: pass instances to read back the postings the loop
    fetched and the evidence it was handed, which is what a deliverable has to be checked
    against."""
    # The guard wraps whatever fetcher the caller supplied — including a cassette's — so the URL
    # policy applies in every mode. Inside the cassette it would be skipped on replay, which is
    # the only mode CI runs.
    fetcher = GuardedFetcher(fetcher or HttpFetcher())
    if fetch is not None and not isinstance(fetch.fetcher, GuardedFetcher):
        # A caller passing `fetch` replaces the tool this function would have built, and with it
        # the guard built two lines up — which is silent, because everything still works. It is
        # how the evaluation harness ran unguarded through a whole stage of security work: the
        # inner `HttpFetcher` re-checks each hop on a live run, so nothing looked wrong, while a
        # cassette in `replay` has no inner fetcher and checked nothing at all. Refusing the
        # combination is the only version of this that cannot be forgotten again.
        raise ValueError(
            "fetch= replaces the guarded fetcher this function builds; wrap its fetcher in "
            "GuardedFetcher before passing it in"
        )
    structurer = structurer or AnthropicStructurer()
    github = github or GitHubClient(cache=DiskCache(config.CACHE_DIR))
    return [
        fetch
        or FetchJobPosting(
            fetcher=fetcher, structurer=structurer, extractor=extractor, model=model
        ),
        ReadCV(structurer=structurer, readable=readable, model=model),
        evidence or GithubEvidence(client=github),
        submit or SubmitReport(),
    ]
