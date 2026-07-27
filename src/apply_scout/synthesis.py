"""Turn gathered evidence into the two deliverables: a match report and a cover letter.

Both are produced by structuring an LLM response into a contract (same validate-and-retry
machinery the tools use), so they are testable with a scripted structurer and no network.
The letter is generated to use *only* facts from the report, and each factual sentence is
asked to cite the evidence link that backs it — which the deterministic guardrail
(`apply_scout.guardrail`) then verifies.
"""

from __future__ import annotations

import json

from apply_scout.contracts import CoverLetterDraft, CVProfile, Evidence, JobPosting, MatchReport
from apply_scout.structuring import Structurer, structure

_REPORT_INSTRUCTIONS = """You are a hiring analyst. Given a job posting, the candidate's CV, and \
the evidence gathered from their GitHub, produce a MatchReport: for EVERY requirement, one \
assessment with a rating (strong / weak / none) and the evidence (with its link) that justifies \
it. Rate `none` when there is no supporting evidence — never invent evidence or a link. Base every \
assessment only on the data provided."""

_LETTER_INSTRUCTIONS = """Write a short, honest cover letter as a CoverLetterDraft (a list of \
sentences), using ONLY facts present in the provided match report. For any sentence that states \
a concrete skill or achievement, set `evidence_urls` to the exact evidence link(s) from the \
report that back it. Connective sentences (greeting, motivation, closing) make no factual claim \
and carry empty `evidence_urls`. NEVER claim a skill or achievement that is not backed by a \
strong or weak assessment with a real evidence link in the report."""


def _report_content(job: JobPosting, cv: CVProfile, evidence: list[Evidence]) -> str:
    return json.dumps(
        {
            "job": job.model_dump(mode="json"),
            "cv": cv.model_dump(mode="json"),
            "evidence": [e.model_dump(mode="json") for e in evidence],
        },
        indent=2,
    )


def generate_match_report(
    job: JobPosting,
    cv: CVProfile,
    evidence: list[Evidence],
    *,
    structurer: Structurer,
    model: str,
    max_attempts: int,
) -> MatchReport:
    """Structure the gathered data into a MatchReport (requirement -> evidence -> rating)."""
    report = structure(
        _report_content(job, cv, evidence),
        MatchReport,
        structurer=structurer,
        model=model,
        instructions=_REPORT_INSTRUCTIONS,
        max_attempts=max_attempts,
    )
    # Anchor the report's identity to the real posting, not whatever the model echoed.
    return report.model_copy(update={"job_title": job.title, "job_url": job.url})


def generate_cover_letter(
    report: MatchReport,
    *,
    structurer: Structurer,
    model: str,
    max_attempts: int,
) -> CoverLetterDraft:
    """Draft a cover letter from the report's facts, with per-sentence evidence citations."""
    return structure(
        report.model_dump_json(),
        CoverLetterDraft,
        structurer=structurer,
        model=model,
        instructions=_LETTER_INSTRUCTIONS,
        max_attempts=max_attempts,
    )
