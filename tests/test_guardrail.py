"""The anti-hallucination guardrail: catch a fabricated citation, and measure it."""

from __future__ import annotations

from apply_scout.contracts import (
    CoverLetterDraft,
    Evidence,
    EvidenceKind,
    LetterSentence,
    MatchAssessment,
    MatchReport,
    Rating,
    Requirement,
)
from apply_scout.guardrail import guardrail_letter, valid_evidence_urls


def _report(url: str) -> MatchReport:
    return MatchReport(
        job_title="Junior Python Developer",
        job_url="https://example.com/job",
        assessments=(
            MatchAssessment(
                requirement=Requirement(text="Python"),
                rating=Rating.STRONG,
                evidence=(Evidence(requirement="Python", kind=EvidenceKind.REPO, url=url),),
            ),
        ),
    )


def test_valid_urls_collects_report_evidence():
    report = _report("https://github.com/u/car-price-ml")
    assert valid_evidence_urls(report) == {"https://github.com/u/car-price-ml"}


def test_removes_sentence_with_fabricated_citation():
    report = _report("https://github.com/u/car-price-ml")
    letter = CoverLetterDraft(
        sentences=(
            LetterSentence(
                text="I built a FastAPI service.",
                evidence_urls=("https://github.com/u/car-price-ml",),  # grounded
            ),
            LetterSentence(
                text="I led a team of 50 engineers.",
                evidence_urls=("https://github.com/u/FABRICATED",),  # hallucinated citation
            ),
            LetterSentence(text="I would love to join your team."),  # connective, no claim
        )
    )
    result = guardrail_letter(letter, report)

    assert len(result.removed) == 1
    assert "50 engineers" in result.removed[0].text
    assert len(result.filtered.sentences) == 2
    assert result.unsupported_before == 1 / 3  # the measurement: 1 of 3 was ungrounded
    assert result.unsupported_after == 0.0


def test_keeps_everything_when_all_grounded():
    report = _report("https://github.com/u/car-price-ml")
    letter = CoverLetterDraft(
        sentences=(
            LetterSentence(text="Hello,"),  # connective
            LetterSentence(
                text="I use FastAPI.",
                evidence_urls=("https://github.com/u/car-price-ml",),
            ),
        )
    )
    result = guardrail_letter(letter, report)

    assert result.removed == ()
    assert result.unsupported_before == 0.0
    assert all(sentence.supported for sentence in result.filtered.sentences)
