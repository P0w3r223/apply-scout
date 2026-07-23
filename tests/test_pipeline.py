"""The deterministic assessment pipeline end to end, with fakes for every dependency."""

from __future__ import annotations

import base64

import httpx
import pytest
from fakes import ScriptedStructurer

from apply_scout.fetch import HttpFetcher
from apply_scout.github import GitHubClient
from apply_scout.pipeline import PipelineError, assess

POSTING_HTML = (
    "<html><body><article><h1>Junior Python Developer</h1>"
    "<p>Python, FastAPI.</p></article></body></html>"
)
JOB_JSON = (
    '{"url": "https://echoed/x", "title": "Junior Python Developer", '
    '"requirements": [{"text": "Python"}, {"text": "FastAPI"}]}'
)
CV_JSON = '{"name": "Patryk", "skills": ["Python", "FastAPI"]}'
REPORT_JSON = (
    '{"job_title": "X", "job_url": "https://x", "assessments": ['
    '{"requirement": {"text": "Python"}, "rating": "strong", "evidence": ['
    '{"requirement": "Python", "kind": "repo", "url": "https://github.com/u/car-price-ml"}]}]}'
)
LETTER_JSON = (
    '{"sentences": ['
    '{"text": "I use Python.", "evidence_urls": ["https://github.com/u/car-price-ml"]}, '
    '{"text": "Kind regards."}]}'
)


def _fetcher(html: str, *, status: int = 200) -> HttpFetcher:
    handler = lambda request: httpx.Response(  # noqa: E731
        status, headers={"content-type": "text/html"}, text=html
    )
    return HttpFetcher(client=httpx.Client(transport=httpx.MockTransport(handler)))


def _github() -> GitHubClient:
    readme = base64.b64encode(b"Built with FastAPI and Python.").decode()

    def handler(request):
        path = request.url.path
        if path.endswith("/repos"):
            page = int(request.url.params.get("page", "1"))
            if page == 1:
                return httpx.Response(
                    200,
                    json=[{"name": "car-price-ml", "full_name": "u/car-price-ml",
                           "language": "Python", "html_url": "https://github.com/u/car-price-ml"}],
                )
            return httpx.Response(200, json=[])
        if path == "/repos/u/car-price-ml/readme":
            return httpx.Response(
                200,
                json={"content": readme, "encoding": "base64",
                      "html_url": "https://github.com/u/car-price-ml/blob/main/README.md"},
            )
        return httpx.Response(404, json={"message": "Not Found"})

    return GitHubClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_assess_end_to_end(tmp_path):
    cv_file = tmp_path / "cv.md"
    cv_file.write_text("Patryk: Python, FastAPI.", encoding="utf-8")
    structurer = ScriptedStructurer([JOB_JSON, CV_JSON, REPORT_JSON, LETTER_JSON])

    result = assess(
        job_url="https://real/job",
        cv_path=str(cv_file),
        github_user="u",
        fetcher=_fetcher(POSTING_HTML),
        structurer=structurer,
        github=_github(),
    )

    assert structurer.calls == 4  # fetch, read_cv, report, letter (github uses no structurer)
    assert result.posting.url == "https://real/job"
    assert result.report.job_title == "Junior Python Developer"
    assert len(result.letter.sentences) == 2  # both grounded -> kept
    assert result.guardrail.unsupported_before == 0.0


def test_assess_raises_when_a_required_step_fails(tmp_path):
    structurer = ScriptedStructurer([JOB_JSON])  # not reached — fetch fails first
    with pytest.raises(PipelineError):
        assess(
            job_url="https://real/job",
            cv_path=str(tmp_path / "cv.md"),
            github_user="u",
            fetcher=_fetcher("nope", status=404),
            structurer=structurer,
            github=_github(),
        )
