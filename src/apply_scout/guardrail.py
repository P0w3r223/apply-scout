"""The anti-hallucination guardrail — deterministic, and measured.

A cover letter may only make claims backed by evidence in the match report. This module
verifies that mechanically (no LLM in the loop): a sentence that cites an evidence link
not present in the report is a hallucinated citation and is removed. A sentence that cites
nothing is treated as connective (a greeting or motivation with no factual claim) and kept.

The point is the *measurement*: `unsupported_before` is the fraction of sentences whose
citations don't hold up; `unsupported_after` is the same fraction once the guardrail has
run (0.0 by construction). Report both — it's the differentiator over "looks fine to me".
"""

from __future__ import annotations

from dataclasses import dataclass

from apply_scout.contracts import CoverLetterDraft, LetterSentence, MatchReport


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
