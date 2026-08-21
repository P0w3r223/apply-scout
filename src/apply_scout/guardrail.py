"""The anti-hallucination guardrail — deterministic, and measured.

Two links in the same chain, both checked without an LLM:

*Letter against report.* A cover letter may only make claims backed by evidence in the
match report. A sentence citing an evidence link absent from the report is a hallucinated
citation and is removed; a sentence citing nothing is connective (a greeting or a
motivation with no factual claim) and is kept. The point is the *measurement*:
`unsupported_before` is the fraction of sentences whose citations don't hold up,
`unsupported_after` the same fraction once filtering has run (0.0 by construction).

*Report against posting.* The link the guardrail used to be blind to. On a page it could
not read, the agent rated ten requirements taken from the **candidate's own CV** and wrote
a letter citing that invented report — and the letter check passed it, because those
citations really did point at the report. Only the report was fiction. `requirement_grounding`
measures the missing half: how much of what a report rates traces back to the posting that
was actually fetched. It is a measurement, not a filter — nothing is removed on its say-so.
"""

from __future__ import annotations

from dataclasses import dataclass

from apply_scout.contracts import CoverLetterDraft, JobPosting, LetterSentence, MatchReport
from apply_scout.matching import mentions


def valid_evidence_urls(report: MatchReport) -> set[str]:
    """Every real evidence link the report actually cites — the ground truth for the letter."""
    return {
        evidence.url
        for assessment in report.assessments
        for evidence in assessment.evidence
        if evidence.url
    }


def _is_grounded(sentence: LetterSentence, valid_urls: set[str]) -> bool:
    # No citation -> a connective sentence with no factual claim to verify -> keep.
    # Otherwise every cited URL must be a real evidence link from the report.
    if not sentence.evidence_urls:
        return True
    return all(url in valid_urls for url in sentence.evidence_urls)


@dataclass(frozen=True)
class GuardrailResult:
    filtered: CoverLetterDraft  # the letter with unsupported sentences removed
    removed: tuple[LetterSentence, ...]  # what was cut, kept for transparency
    unsupported_before: float  # fraction of sentences with a citation not backed by the report
    unsupported_after: float  # fraction remaining after filtering (0.0 by construction)


def guardrail_letter(letter: CoverLetterDraft, report: MatchReport) -> GuardrailResult:
    """Remove sentences whose citations aren't backed by the report; measure before/after."""
    valid = valid_evidence_urls(report)
    total = len(letter.sentences)

    kept: list[LetterSentence] = []
    removed: list[LetterSentence] = []
    for sentence in letter.sentences:
        if _is_grounded(sentence, valid):
            # Record the guardrail's own verdict, not the model's self-assessment.
            kept.append(sentence.model_copy(update={"supported": True}))
        else:
            removed.append(sentence)

    unsupported_before = (len(removed) / total) if total else 0.0
    return GuardrailResult(
        filtered=CoverLetterDraft(sentences=tuple(kept)),
        removed=tuple(removed),
        unsupported_before=unsupported_before,
        unsupported_after=0.0,
    )


def _traces_to(requirement: str, posting: JobPosting) -> bool:
    """Whether a rated requirement can be found in the posting that was fetched.

    Matched both ways round because the two sides are written by different authors: the
    pipeline copies the posting's own wording, while the loop paraphrases ("Python" rated
    against "Strong Python for AI/ML workloads", or the reverse). Demanding one direction
    would score the phrasing rather than the provenance.
    """
    return any(
        mentions(candidate.text, requirement) or mentions(requirement, candidate.text)
        for candidate in posting.requirements
    )


def requirement_grounding(report: MatchReport, posting: JobPosting | None) -> float | None:
    """Of the requirements the report rates, the fraction traceable to the fetched posting.

    `None` only when the report rates nothing — there is no claim to ground, and scoring
    an empty report is scoring nothing.

    **A report that rates requirements with no posting behind it scores 0.0, not `n/a`.**
    That is the failure this metric exists for: on the JavaScript-only page `fetch_job_posting`
    returns an error (no readable text), so the loop never held a posting at all — and rated
    ten requirements anyway. Calling that "not applicable" would let the exact case the
    metric was built to catch slip out of the mean.

    Matching is `matching.mentions`, which is crude: a fabricated requirement that happens
    to echo the posting's wording counts as grounded. This bounds *untraceable* claims, in
    the same way the letter check bounds unsupported citations rather than proving truth.
    """
    rated = [assessment.requirement.text for assessment in report.assessments]
    if not rated:
        return None
    if posting is None or not posting.requirements:
        return 0.0
    return sum(_traces_to(requirement, posting) for requirement in rated) / len(rated)
