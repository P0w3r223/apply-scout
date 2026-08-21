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
from apply_scout.github import DiskCache, GitHubClient
from apply_scout.tools.fetch_job_posting import FetchJobPosting
from apply_scout.tools.read_cv import ReadCV
from apply_scout.tools.real import real_tools

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


def test_fetch_job_posting_keeps_what_it_returned():
    """The posting the caller can read back afterwards — the independent side of the
    grounding check. The trajectory keeps only a log-safe summary, so this attribute is
    the sole way to recover what the loop was actually told the ad said."""
    tool = FetchJobPosting(
        fetcher=_fetcher(POSTING_HTML), structurer=ScriptedStructurer([POSTING_JSON])
    )
    assert tool.fetched is None  # nothing fetched yet is a state, not an absence of one

    tool.run({"url": "https://real.example/job"})
    assert tool.fetched is not None
    assert tool.fetched.url == "https://real.example/job"  # the corrected URL, not the echo
    assert [r.text for r in tool.fetched.requirements] == ["Python", "FastAPI"]


def test_a_failed_fetch_keeps_no_posting():
    """A run that could not read the ad must not look like one that did — that difference
    is what turns a fabricated report into a 0.00 rather than an `n/a`."""
    tool = FetchJobPosting(
        fetcher=_fetcher("<html><body></body></html>"), structurer=ScriptedStructurer([])
    )
    assert not tool.run({"url": "https://real.example/job"}).ok
    assert tool.fetched is None


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


def test_capturing_the_posting_leaves_the_tool_spec_untouched():
    """A cassette key hashes `{model, system, messages, tools}`, so the tool spec is part of
    every recorded request. Keeping the posting is an instance attribute — invisible to the
    API — but a nudge to the name, description or schema would miss all 106 recorded entries
    and quietly turn a free replay into a paid re-record. Pinned so that happens loudly."""
    spec = FetchJobPosting(fetcher=_fetcher(POSTING_HTML), structurer=ScriptedStructurer([])).spec()
    assert spec == {
        "name": "fetch_job_posting",
        "description": (
            "Fetch a job posting from a URL and extract its requirements into a JobPosting."
        ),
        "input_schema": {
            "type": "object",
            "title": "FetchJobPostingInput",
            "properties": {
                "url": {
                    "description": "URL of the job posting to fetch.",
                    "title": "Url",
                    "type": "string",
                }
            },
            "required": ["url"],
        },
    }


def test_real_tools_uses_the_injected_fetch_instance(tmp_path):
    """Same arrangement as `submit`: the caller keeps the instance to read it back after
    the run, and the toolset must use that one rather than building its own — otherwise the
    posting is captured on a tool nobody holds."""
    fetch = FetchJobPosting(
        fetcher=_fetcher(POSTING_HTML), structurer=ScriptedStructurer([POSTING_JSON])
    )
    tools = real_tools(
        fetcher=_fetcher(POSTING_HTML),
        structurer=ScriptedStructurer([]),
        github=GitHubClient(cache=DiskCache(tmp_path)),
        fetch=fetch,
    )
    assert next(tool for tool in tools if tool.name == "fetch_job_posting") is fetch


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
