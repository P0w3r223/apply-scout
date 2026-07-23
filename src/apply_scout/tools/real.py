"""Assemble the real toolset for an agent run.

`github_evidence` is still the mock until milestone 3 — the other two are real. This is
the honest current state: two live tools, one stand-in, one loop that doesn't care which
is which because they share the same contracts.
"""

from __future__ import annotations

from apply_scout import config
from apply_scout.fetch import HttpFetcher
from apply_scout.structuring import AnthropicStructurer, Structurer
from apply_scout.tools.base import Tool
from apply_scout.tools.fetch_job_posting import FetchJobPosting
from apply_scout.tools.mock import MockGithubEvidence
from apply_scout.tools.read_cv import ReadCV


def real_tools(
    *,
    fetcher: HttpFetcher | None = None,
    structurer: Structurer | None = None,
    model: str = config.STRUCTURE_MODEL,
) -> list[Tool]:
    """The live tools for a real run. Dependencies default to production wiring but can
    be injected (that is how the tools are tested)."""
    fetcher = fetcher or HttpFetcher()
    structurer = structurer or AnthropicStructurer()
    return [
        FetchJobPosting(fetcher=fetcher, structurer=structurer, model=model),
        ReadCV(structurer=structurer, model=model),
        MockGithubEvidence(),  # real GitHub evidence lands in milestone 3
    ]
