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


def real_tools(
    *,
    fetcher: Fetcher | None = None,
    structurer: Structurer | None = None,
    github: GitHubClient | None = None,
    extractor: Extractor | None = None,
    model: str = config.STRUCTURE_MODEL,
) -> list[Tool]:
    """The live tools for a real run. Defaults to production wiring; inject to test."""
    fetcher = fetcher or HttpFetcher()
    structurer = structurer or AnthropicStructurer()
    github = github or GitHubClient(cache=DiskCache(config.CACHE_DIR))
    return [
        FetchJobPosting(
            fetcher=fetcher, structurer=structurer, extractor=extractor, model=model
        ),
        ReadCV(structurer=structurer, model=model),
        GithubEvidence(client=github),
    ]
