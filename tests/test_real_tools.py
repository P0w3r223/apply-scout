"""The real fetch_job_posting and read_cv tools, end to end with fakes.

Recorded HTTP + a scripted structurer stand in for the network and the model, so every
path — happy, broken structuring, HTTP failure, empty page, missing/empty CV file — is
exercised deterministically.
"""

from __future__ import annotations

import httpx
import pytest
from fakes import ScriptedStructurer

from apply_scout.contracts import CVProfile, JobPosting
from apply_scout.fetch import GuardedFetcher, HttpFetcher
from apply_scout.github import DiskCache, GitHubClient
from apply_scout.tools.fetch_job_posting import FetchJobPosting
from apply_scout.tools.read_cv import ReadCV
from apply_scout.tools.real import real_tools
from apply_scout.tools.registry import ToolRegistry

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
    assert tool.postings == ()  # nothing fetched yet is a state, not an absence of one

    tool.run({"url": "https://real.example/job"})
    assert len(tool.postings) == 1
    assert tool.postings[0].url == "https://real.example/job"  # the corrected URL, not the echo
    assert [r.text for r in tool.postings[0].requirements] == ["Python", "FastAPI"]


def test_a_re_fetch_does_not_discard_the_earlier_posting():
    """The loop re-fetches — the JavaScript-only task calls this tool twice. Keeping only the
    newest would let a retry that structures to *fewer* requirements erase what the model had
    already read, and the grounding check would then convict a faithful report of inventing
    the difference."""
    thin = '{"url": "https://real.example/job", "title": "Junior Python Developer"}'
    tool = FetchJobPosting(
        fetcher=_fetcher(POSTING_HTML),
        structurer=ScriptedStructurer([POSTING_JSON, thin]),
    )
    tool.run({"url": "https://real.example/job"})
    tool.run({"url": "https://real.example/job"})

    assert len(tool.postings) == 2
    assert [len(p.requirements) for p in tool.postings] == [2, 0]


def test_a_failed_fetch_keeps_no_posting():
    """A run that could not read the ad must not look like one that did — that difference
    is what turns a fabricated report into a 0.00 rather than an `n/a`."""
    tool = FetchJobPosting(
        fetcher=_fetcher("<html><body></body></html>"), structurer=ScriptedStructurer([])
    )
    assert not tool.run({"url": "https://real.example/job"}).ok
    assert tool.postings == ()


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
    posting is captured on a tool nobody holds.

    The injected tool has to carry the guard itself, since using it means not using the one
    `real_tools` built."""
    fetch = FetchJobPosting(
        fetcher=GuardedFetcher(_fetcher(POSTING_HTML)),
        structurer=ScriptedStructurer([POSTING_JSON]),
    )
    tools = real_tools(
        readable=[tmp_path / "cv.md"],
        fetcher=_fetcher(POSTING_HTML),
        structurer=ScriptedStructurer([]),
        github=GitHubClient(cache=DiskCache(tmp_path)),
        fetch=fetch,
    )
    assert next(tool for tool in tools if tool.name == "fetch_job_posting") is fetch


def test_an_injected_fetch_without_the_guard_is_refused(tmp_path):
    """The trap this closes was live for a whole stage of security work: `real_tools` built a
    `GuardedFetcher` and then discarded it whenever `fetch=` was passed, which is what the
    evaluation harness does. Nothing broke, because a live `HttpFetcher` re-checks every hop
    itself — but under a cassette in `replay` there is no inner fetcher and no check at all."""
    unguarded = FetchJobPosting(
        fetcher=_fetcher(POSTING_HTML), structurer=ScriptedStructurer([POSTING_JSON])
    )
    with pytest.raises(ValueError, match="GuardedFetcher"):
        real_tools(
            readable=[tmp_path / "cv.md"],
            structurer=ScriptedStructurer([]),
            github=GitHubClient(cache=DiskCache(tmp_path)),
            fetch=unguarded,
        )


@pytest.mark.parametrize("inject_fetch", [False, True])
def test_the_assembled_toolset_refuses_a_blocked_url(tmp_path, inject_fetch):
    """Asserted on what `real_tools` returns, not on `GuardedFetcher` in isolation.

    `read_cv`'s confinement has had a spec-pinning test since it landed; the fetch half had
    only a unit test of the wrapper, which is why a caller could drop it unnoticed. The
    recording fetcher is the evidence: a refusal that still reached the network would be a
    refusal reported after the fact."""
    reached: list[str] = []

    class Recording:
        def get(self, url: str) -> str:
            reached.append(url)
            return POSTING_HTML

    kwargs = {}
    if inject_fetch:
        kwargs["fetch"] = FetchJobPosting(
            fetcher=GuardedFetcher(Recording()), structurer=ScriptedStructurer([])
        )
    tools = real_tools(
        readable=[tmp_path / "cv.md"],
        fetcher=Recording(),
        structurer=ScriptedStructurer([]),
        github=GitHubClient(cache=DiskCache(tmp_path)),
        **kwargs,
    )
    result = ToolRegistry(tools).dispatch(
        "fetch_job_posting", {"url": "http://169.254.169.254/latest/meta-data/"}
    )
    assert not result.ok
    assert reached == []


def test_read_cv_happy_path(tmp_path):
    cv_file = tmp_path / "cv.md"
    cv_file.write_text("Patryk — Python, FastAPI, SQL.", encoding="utf-8")
    cv_json = '{"name": "Patryk", "skills": ["Python", "FastAPI", "SQL"]}'
    tool = ReadCV(structurer=ScriptedStructurer([cv_json]), readable=[cv_file])

    result = tool.run({"path": str(cv_file)})
    assert result.ok
    cv = CVProfile.model_validate_json(result.content)
    assert cv.name == "Patryk"
    assert len(cv.skills) == 3


def test_read_cv_missing_file_is_structured(tmp_path):
    missing = tmp_path / "nope.md"
    tool = ReadCV(structurer=ScriptedStructurer([]), readable=[missing])
    result = tool.run({"path": str(missing)})
    assert not result.ok
    assert "not found" in result.content


def test_read_cv_empty_file_is_structured(tmp_path):
    cv_file = tmp_path / "empty.md"
    cv_file.write_text("   \n", encoding="utf-8")
    tool = ReadCV(structurer=ScriptedStructurer([]), readable=[cv_file])
    result = tool.run({"path": str(cv_file)})
    assert not result.ok
    assert "empty" in result.content


# --- what `read_cv` may open ------------------------------------------------------------
# The path is a tool argument the model picks out of a conversation that carries fetched web
# text, and the file's contents go straight back to the model. The caller names the CV at
# startup (`--cv`), so the argument is a selector over files already chosen, not a free path.


def test_read_cv_refuses_a_file_outside_the_allowlist(tmp_path):
    cv_file = tmp_path / "cv.md"
    cv_file.write_text("Patryk — Python.", encoding="utf-8")
    secret = tmp_path / "id_rsa"
    secret.write_text("PRIVATE KEY", encoding="utf-8")

    tool = ReadCV(structurer=ScriptedStructurer([]), readable=[cv_file])
    result = tool.run({"path": str(secret)})

    assert not result.ok
    assert "may read" in result.content
    assert "PRIVATE KEY" not in result.content


def test_read_cv_refuses_a_traversal_that_lands_outside(tmp_path):
    """`..` is resolved before the comparison, so a path that *spells* its way out is judged
    by where it lands rather than by how it is written."""
    inside = tmp_path / "cvs"
    inside.mkdir()
    cv_file = inside / "cv.md"
    cv_file.write_text("Patryk — Python.", encoding="utf-8")
    secret = tmp_path / "id_rsa"
    secret.write_text("PRIVATE KEY", encoding="utf-8")

    tool = ReadCV(structurer=ScriptedStructurer([]), readable=[cv_file])
    result = tool.run({"path": str(inside / ".." / "id_rsa")})

    assert not result.ok
    assert "may read" in result.content


def test_read_cv_accepts_another_spelling_of_the_allowed_file(tmp_path):
    """The same normalisation cuts the other way: the allowed file stays readable when the
    model writes its path differently from the way the caller did."""
    inside = tmp_path / "cvs"
    inside.mkdir()
    cv_file = inside / "cv.md"
    cv_file.write_text("Patryk — Python, FastAPI, SQL.", encoding="utf-8")
    cv_json = '{"name": "Patryk", "skills": ["Python"]}'

    tool = ReadCV(structurer=ScriptedStructurer([cv_json]), readable=[cv_file])
    result = tool.run({"path": str(inside / ".." / "cvs" / "cv.md")})

    assert result.ok


def test_confining_read_cv_leaves_its_tool_spec_untouched():
    """The sibling of the `fetch_job_posting` pin above, and the reason the allowlist is a
    constructor argument rather than a second field on `ReadCVInput`. A cassette key hashes
    `{model, system, messages, tools}`, so widening the input model to carry a base directory
    would miss every recorded entry and turn a free replay into a paid re-record. What the
    model sees is unchanged; what the tool honours is not."""
    spec = ReadCV(structurer=ScriptedStructurer([]), readable=[]).spec()
    assert spec == {
        "name": "read_cv",
        "description": "Parse the candidate's CV file into a structured, searchable profile.",
        "input_schema": {
            "type": "object",
            "title": "ReadCVInput",
            "properties": {
                "path": {
                    "description": "Path to the candidate's CV file (text or markdown).",
                    "title": "Path",
                    "type": "string",
                }
            },
            "required": ["path"],
        },
    }
