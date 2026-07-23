"""The real fetch_job_posting and read_cv tools, end to end with fakes.

Recorded HTTP + a scripted structurer stand in for the network and the model, so every
path — happy, broken structuring, HTTP failure, empty page, missing/empty CV file — is
exercised deterministically.
"""

from __future__ import annotations

import httpx
from fakes import ScriptedStructurer

from apply_scout.contracts import CVProfile, JobPosting
from apply_scout.fetch import HttpFetcher
from apply_scout.tools.fetch_job_posting import FetchJobPosting
from apply_scout.tools.read_cv import ReadCV

POSTING_HTML = (
    "<html><body><article><h1>Junior Python Developer</h1>"
    "<p>Python, FastAPI, SQL.</p></article></body></html>"
)
# Note the model echoes a wrong URL — the tool must overwrite it with the fetched one.
POSTING_JSON = (
    '{"url": "https://echoed-wrong.example/x", "title": "Junior Python Developer", '
    '"requirements": [{"text": "Python"}, {"text": "FastAPI"}]}'
)


def _fetcher(html: str, *, status: int = 200, content_type: str = "text/html") -> HttpFetcher:
    handler = lambda request: httpx.Response(  # noqa: E731
        status, headers={"content-type": content_type}, text=html
    )
    return HttpFetcher(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_fetch_job_posting_happy_path():
    tool = FetchJobPosting(
        fetcher=_fetcher(POSTING_HTML), structurer=ScriptedStructurer([POSTING_JSON])
    )
    result = tool.run({"url": "https://real.example/job"})

    assert result.ok
    posting = JobPosting.model_validate_json(result.content)
    assert posting.title == "Junior Python Developer"
    assert posting.url == "https://real.example/job"  # our URL wins over the model's echo
    assert len(posting.requirements) == 2


def test_fetch_job_posting_unstructurable_text_is_error():
    tool = FetchJobPosting(
        fetcher=_fetcher(POSTING_HTML),
        structurer=ScriptedStructurer(['{"bad": 1}', '{"bad": 2}', '{"bad": 3}']),
        max_attempts=3,
    )
    result = tool.run({"url": "https://real.example/job"})
    assert not result.ok
    assert "could not structure" in result.content


def test_fetch_job_posting_http_error_is_structured():
    tool = FetchJobPosting(fetcher=_fetcher("nope", status=404), structurer=ScriptedStructurer([]))
    result = tool.run({"url": "https://real.example/job"})
    assert not result.ok
    assert "Could not fetch" in result.content


def test_fetch_job_posting_empty_page_is_structured():
    tool = FetchJobPosting(
        fetcher=_fetcher("<html><body></body></html>"), structurer=ScriptedStructurer([])
    )
    result = tool.run({"url": "https://real.example/job"})
    assert not result.ok
    assert "no readable text" in result.content


def test_read_cv_happy_path(tmp_path):
    cv_file = tmp_path / "cv.md"
    cv_file.write_text("Patryk — Python, FastAPI, SQL.", encoding="utf-8")
    cv_json = '{"name": "Patryk", "skills": ["Python", "FastAPI", "SQL"]}'
    tool = ReadCV(structurer=ScriptedStructurer([cv_json]))

    result = tool.run({"path": str(cv_file)})
    assert result.ok
    cv = CVProfile.model_validate_json(result.content)
    assert cv.name == "Patryk"
    assert len(cv.skills) == 3


def test_read_cv_missing_file_is_structured(tmp_path):
    tool = ReadCV(structurer=ScriptedStructurer([]))
    result = tool.run({"path": str(tmp_path / "nope.md")})
    assert not result.ok
    assert "not found" in result.content


def test_read_cv_empty_file_is_structured(tmp_path):
    cv_file = tmp_path / "empty.md"
    cv_file.write_text("   \n", encoding="utf-8")
    tool = ReadCV(structurer=ScriptedStructurer([]))
    result = tool.run({"path": str(cv_file)})
    assert not result.ok
    assert "empty" in result.content
