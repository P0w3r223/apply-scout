"""Assemble the real toolset for an agent run.

As of milestone 3 all three tools are live (fetch posting, read CV, GitHub evidence).
Dependencies default to production wiring but can be injected — which is how the tools
are tested — and they all share the same contracts, so the agent loop is unchanged.
"""

from __future__ import annotations

from apply_scout import config
from apply_scout.fetch import Extractor, Fetcher, HttpFetcher
from apply_scout.github import DiskCache, GitHubClient
from apply_scout.structuring import AnthropicStructurer, Structurer
from apply_scout.tools.base import Tool
from apply_scout.tools.fetch_job_posting import FetchJobPosting
from apply_scout.tools.github_evidence import GithubEvidence
from apply_scout.tools.read_cv import ReadCV
from apply_scout.tools.submit_report import SubmitReport


def real_tools(
    *,
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
    fetcher = fetcher or HttpFetcher()
    structurer = structurer or AnthropicStructurer()
    github = github or GitHubClient(cache=DiskCache(config.CACHE_DIR))
    return [
        fetch
        or FetchJobPosting(
            fetcher=fetcher, structurer=structurer, extractor=extractor, model=model
        ),
        ReadCV(structurer=structurer, model=model),
        evidence or GithubEvidence(client=github),
        submit or SubmitReport(),
    ]
