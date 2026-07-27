"""Report and letter generation (structured via a scripted structurer)."""

from __future__ import annotations

from fakes import ScriptedStructurer

from apply_scout.contracts import CVProfile, JobPosting, MatchReport, Requirement
from apply_scout.synthesis import generate_cover_letter, generate_match_report

REPORT_JSON = (
    '{"job_title": "echoed", "job_url": "https://echoed", "assessments": ['
    '{"requirement": {"text": "Python"}, "rating": "strong", "evidence": ['
    '{"requirement": "Python", "kind": "repo", "url": "https://github.com/u/car-price-ml"}]}]}'
)
LETTER_JSON = (
    '{"sentences": ['
    '{"text": "I use Python.", "evidence_urls": ["https://github.com/u/car-price-ml"]}, '
    '{"text": "Kind regards."}]}'
)


def test_generate_match_report_anchors_job_identity():
    job = JobPosting(
        url="https://real/job",
        title="Junior Python Developer",
        requirements=(Requirement(text="Python"),),
    )
    cv = CVProfile(skills=("Python",))
    report = generate_match_report(
        job, cv, [], structurer=ScriptedStructurer([REPORT_JSON]), model="m", max_attempts=3
    )
    # The model's echoed title/url are overwritten with the real posting's.
    assert report.job_title == "Junior Python Developer"
    assert report.job_url == "https://real/job"
    assert report.assessments[0].rating.value == "strong"


def test_generate_cover_letter_carries_citations():
    report = MatchReport.model_validate_json(REPORT_JSON)
    letter = generate_cover_letter(
        report, structurer=ScriptedStructurer([LETTER_JSON]), model="m", max_attempts=3
    )
    assert len(letter.sentences) == 2
    assert letter.sentences[0].evidence_urls == ("https://github.com/u/car-price-ml",)
