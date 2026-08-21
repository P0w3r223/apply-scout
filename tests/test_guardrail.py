"""The anti-hallucination guardrail: catch a fabricated citation, and measure it.

Two links: the letter against the report, and the report against the posting it claims to
describe. The second exists because a letter can cite a report perfectly while the report
itself was invented out of the candidate's CV.
"""

from __future__ import annotations

from apply_scout.contracts import (
    CoverLetterDraft,
    Evidence,
    EvidenceKind,
    JobPosting,
    LetterSentence,
    MatchAssessment,
    MatchReport,
    Rating,
    Requirement,
)
from apply_scout.guardrail import guardrail_letter, requirement_grounding, valid_evidence_urls


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


def _rated(*requirements: str) -> MatchReport:
    """A report that rates the given requirements, evidence aside — grounding ignores it."""
    return MatchReport(
        job_title="X",
        job_url="https://example.com/job",
        assessments=tuple(
            MatchAssessment(requirement=Requirement(text=text), rating=Rating.NONE)
            for text in requirements
        ),
    )


def _posting(*requirements: str) -> JobPosting:
    return JobPosting(
        url="https://example.com/job",
        title="X",
        requirements=tuple(Requirement(text=text) for text in requirements),
    )


def test_a_report_of_the_posting_is_fully_grounded():
    """Both directions count: the pipeline copies the posting's wording, the loop paraphrases."""
    report = _rated("Python", "Experience with FastAPI in production")
    posting = _posting("Strong Python for AI/ML workloads", "FastAPI")
    assert requirement_grounding(report, (posting,)) == 1.0


def test_a_requirement_the_posting_never_asked_for_is_not_grounded():
    report = _rated("Python", "Fifteen years of Haskell")
    assert requirement_grounding(report, (_posting("Python", "FastAPI"),)) == 0.5


def test_grounding_reads_every_posting_the_run_fetched_not_just_the_last():
    """A retry that yields less must not erase what the model already read. Scored against
    the newest posting alone, this report would read 0.00 — the maximum fabrication verdict
    for a run that rated exactly what the first fetch returned."""
    report = _rated("Python", "FastAPI")
    first, retry = _posting("Python", "FastAPI"), _posting()
    assert requirement_grounding(report, (first, retry)) == 1.0
    assert requirement_grounding(report, (retry,)) == 0.0  # what the bug used to score


def test_rating_requirements_with_no_posting_scores_zero_not_n_a():
    """The failure this metric exists for: on the JavaScript-only page `fetch_job_posting`
    errors out, the loop never holds a posting — and rates ten requirements anyway. Calling
    that "not applicable" would drop the one run the metric was built to catch."""
    report = _rated("Python", "FastAPI", "Docker")
    assert requirement_grounding(report, ()) == 0.0
    # Same verdict for a posting that was fetched but yielded nothing to rate against.
    assert requirement_grounding(report, (_posting(),)) == 0.0


def test_a_report_that_rates_nothing_has_no_grounding_to_measure():
    """No claim, nothing to ground — distinct from an ungrounded claim, and scored as such."""
    assert requirement_grounding(_rated(), (_posting("Python"),)) is None
    assert requirement_grounding(_rated(), ()) is None
