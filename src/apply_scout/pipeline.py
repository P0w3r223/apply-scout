"""The deterministic assessment pipeline: gather -> synthesize -> guard.

Where the agent loop (`runner`) lets the model orchestrate the tools and yields a
trajectory, this pipeline runs the same real tools in a fixed order to reliably produce
the structured deliverables: a `MatchReport`, a cover letter, and the guardrail's
measurement. Everything is injectable, so the whole path is tested with fakes — no
network, no key. LLM extraction (fetch/CV) runs on the cheap model; the higher-stakes
report and letter run on the agent model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from apply_scout import config
from apply_scout.contracts import CoverLetterDraft, CVProfile, Evidence, JobPosting, MatchReport
from apply_scout.fetch import Extractor, Fetcher, GuardedFetcher, HttpFetcher
from apply_scout.github import DiskCache, GitHubClient
from apply_scout.guardrail import GuardrailResult, guardrail_letter
from apply_scout.structuring import AnthropicStructurer, Structurer
from apply_scout.synthesis import generate_cover_letter, generate_match_report
from apply_scout.tools.base import PydanticTool
from apply_scout.tools.fetch_job_posting import FetchJobPosting
from apply_scout.tools.github_evidence import GithubEvidence
from apply_scout.tools.read_cv import ReadCV


class PipelineError(Exception):
    """A required gathering step failed (bad URL, missing CV, …)."""


@dataclass(frozen=True)
class Assessment:
    posting: JobPosting  # what the run claims the posting asked for
    cv: CVProfile
    report: MatchReport
    letter: CoverLetterDraft  # already guardrailed
    guardrail: GuardrailResult
    # Everything `fetch_job_posting` returned during the run. Separate from `posting` because
    # the two are not the same claim: on the agent path `posting` is reconstructed from the
    # report itself (see `evaluation.agent_assess_fn`), so checking a report against it would
    # ask a document to confirm itself.
    #
    # Required, deliberately: `requirement_grounding` reads "nothing fetched" as its
    # fabrication verdict, so a default would let a caller who merely forgot to wire this up
    # score a clean report 0.00. An empty tuple has to be something a caller *states*.
    source_postings: tuple[JobPosting, ...]
    # Everything `github_evidence` handed back during the run. Required for the same reason:
    # `evidence_grounding` reads "nothing retrieved" as its fabrication verdict, so this must
    # be stated rather than defaulted.
    source_evidence: tuple[Evidence, ...]


def _tool_json(tool: PydanticTool, raw_input: dict, model_cls: type) -> object:
    result = tool.run(raw_input)
    if not result.ok:
        raise PipelineError(result.content)
    return model_cls.model_validate_json(result.content)


def assess(
    *,
    job_url: str,
    cv_path: str,
    github_user: str,
    fetcher: Fetcher | None = None,
    structurer: Structurer | None = None,
    github: GitHubClient | None = None,
    extractor: Extractor | None = None,
    model: str = config.DEFAULT_MODEL,
    structure_model: str = config.STRUCTURE_MODEL,
    max_attempts: int = config.STRUCTURE_MAX_ATTEMPTS,
) -> Assessment:
    """Run a full assessment: fetch + read CV + gather evidence -> report -> letter -> guardrail.

    `model` drives the higher-stakes report/letter; `structure_model` drives the cheaper
    fetch/CV extraction. The eval harness sets them equal to compare a model head to head."""
    # Same guard as the agent path (`real_tools`): the pipeline calls the same tools in a fixed
    # order, so it needs the same URL policy — the order does not make the address trustworthy.
    fetcher = GuardedFetcher(fetcher or HttpFetcher())
    structurer = structurer or AnthropicStructurer()
    github = github or GitHubClient(cache=DiskCache(config.CACHE_DIR))

    posting: JobPosting = _tool_json(  # type: ignore[assignment]
        FetchJobPosting(
            fetcher=fetcher, structurer=structurer, extractor=extractor,
            model=structure_model, max_attempts=max_attempts,
        ),
        {"url": job_url},
        JobPosting,
    )
    cv: CVProfile = _tool_json(  # type: ignore[assignment]
        ReadCV(
            structurer=structurer,
            readable=[cv_path],
            model=structure_model,
            max_attempts=max_attempts,
        ),
        {"path": cv_path},
        CVProfile,
    )

    evidence_tool = GithubEvidence(client=github)
    evidence: list[Evidence] = []
    for requirement in posting.requirements:
        result = evidence_tool.run({"requirement": requirement.text, "github_user": github_user})
        if result.ok:
            for item in json.loads(result.content)["evidence"]:
                evidence.append(Evidence.model_validate(item))

    report = generate_match_report(
        posting, cv, evidence, structurer=structurer, model=model, max_attempts=max_attempts
    )
    letter = generate_cover_letter(
        report, structurer=structurer, model=model, max_attempts=max_attempts
    )
    guard = guardrail_letter(letter, report)
    return Assessment(
        posting=posting,
        cv=cv,
        report=report,
        letter=guard.filtered,
        guardrail=guard,
        # One fetch, by construction: the pipeline rates the posting it fetched. Recording it
        # anyway is what lets the grounding metric be read as a control — a pipeline row below
        # 1.00 means synthesis invented a requirement.
        source_postings=(posting,),
        # The evidence the tool retrieved, before synthesis had a chance to reshape it.
        source_evidence=tuple(evidence),
    )
