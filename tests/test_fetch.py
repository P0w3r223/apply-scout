"""HTTP fetching and content extraction, driven by recorded responses."""

from __future__ import annotations

import httpx
import pytest

from apply_scout.fetch import (
    BlockedUrl,
    FetchError,
    GuardedFetcher,
    HttpFetcher,
    check_resolved,
    check_url,
    extract_main_text,
)

SAMPLE_HTML = """<html><head><title>Job</title><style>.x{color:red}</style></head>
<body><nav>Home About</nav>
<article><h1>Junior Python Developer</h1>
<p>We are looking for Python and FastAPI skills. SQL is nice to have.</p></article>
<script>var secret = 42;</script></body></html>"""


def _fetcher(handler) -> HttpFetcher:
    return HttpFetcher(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_get_returns_html_on_200():
    fetcher = _fetcher(
        lambda r: httpx.Response(200, headers={"content-type": "text/html"}, text=SAMPLE_HTML)
    )
    assert "Junior Python Developer" in fetcher.get("https://example.com/job")


def test_non_200_raises_fetch_error():
    fetcher = _fetcher(
        lambda r: httpx.Response(404, headers={"content-type": "text/html"}, text="x")
    )
    with pytest.raises(FetchError):
        fetcher.get("https://example.com/job")


def test_non_html_content_type_raises():
    fetcher = _fetcher(
        lambda r: httpx.Response(200, headers={"content-type": "application/pdf"}, text="%PDF")
    )
    with pytest.raises(FetchError):
        fetcher.get("https://example.com/job")


def test_extract_keeps_body_text_and_drops_script_style():
    text = extract_main_text(SAMPLE_HTML)
    assert "Python and FastAPI" in text
    assert "var secret" not in text  # <script> content is dropped
    assert "color:red" not in text  # <style> content is dropped


def test_extract_returns_empty_for_contentless_page():
    assert extract_main_text("<html><body></body></html>") == ""


# --- the URL policy ---------------------------------------------------------------------
# `fetch_job_posting` takes its URL from a conversation carrying text off the internet, so the
# address is attacker-influenceable. These assert what may not be requested, and — separately —
# that the refusal happens before anything is fetched.


@pytest.mark.parametrize(
    "url, reason",
    [
        ("file:///etc/passwd", "scheme"),
        ("ftp://example.com/x", "scheme"),
        ("//example.com/x", "scheme"),  # no scheme at all
        ("https://user:pw@example.com/x", "credentials"),
        ("http://localhost/x", "loopback"),
        ("http://build.localhost/x", "loopback"),
        ("http://127.0.0.1/x", "non-public"),
        ("http://169.254.169.254/latest/meta-data/", "non-public"),  # cloud metadata
        ("http://10.1.2.3/x", "non-public"),
        ("http://192.168.0.1/x", "non-public"),
        ("http://[::1]/x", "non-public"),
        ("http://[::ffff:127.0.0.1]/x", "non-public"),  # loopback, written as IPv6
    ],
)
def test_check_url_refuses(url, reason):
    with pytest.raises(BlockedUrl) as excinfo:
        check_url(url)
    assert reason in str(excinfo.value)


def test_check_url_allows_an_ordinary_posting_and_resolves_nothing():
    """No DNS here on purpose: this half of the policy runs at the `Fetcher` seam, which is
    crossed on `replay` too — and replay is guaranteed to make no network call."""
    check_url("https://boards.greenhouse.io/acme/jobs/1")


def test_check_resolved_refuses_a_name_pointing_inside():
    with pytest.raises(BlockedUrl) as excinfo:
        check_resolved("https://evil.example/x", resolve=lambda host: ["127.0.0.1"])
    assert "non-public" in str(excinfo.value)


def test_check_resolved_refuses_when_only_one_address_is_internal():
    """Every address has to be public, not just the first — otherwise a name with one public
    and one loopback record passes the check and then connects to the loopback one."""
    with pytest.raises(BlockedUrl):
        check_resolved(
            "https://mixed.example/x", resolve=lambda host: ["93.184.216.34", "10.0.0.5"]
        )


def test_check_resolved_allows_a_public_name():
    check_resolved("https://ok.example/x", resolve=lambda host: ["93.184.216.34"])


def test_check_resolved_refuses_a_name_that_does_not_resolve():
    def _boom(host):
        raise OSError("nope")

    with pytest.raises(BlockedUrl):
        check_resolved("https://gone.example/x", resolve=_boom)


def test_guarded_fetcher_refuses_before_the_inner_fetcher_is_reached():
    """The point of the wrapper: a blocked address never becomes a request. Asserted by the
    inner fetcher recording nothing, rather than by the exception type alone."""
    seen: list[str] = []

    class _Recording:
        def get(self, url: str) -> str:
            seen.append(url)
            return "<html></html>"

    guarded = GuardedFetcher(_Recording())
    with pytest.raises(BlockedUrl):
        guarded.get("http://169.254.169.254/latest/meta-data/")
    assert seen == []
    guarded.get("https://example.com/job")
    assert seen == ["https://example.com/job"]


# --- redirects --------------------------------------------------------------------------
# A redirect is the ordinary way an allowed URL turns into a forbidden one, and httpx would
# follow the chain internally and hand back only the final response — so the address that was
# checked would not be the address that was fetched.


def _redirect_then(target: str, final: httpx.Response):
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://example.com/job":
            return httpx.Response(302, headers={"location": target})
        return final

    return handler


def test_a_redirect_to_an_internal_address_is_refused():
    fetcher = _fetcher(
        _redirect_then(
            "http://169.254.169.254/latest/meta-data/",
            httpx.Response(200, headers={"content-type": "text/html"}, text="secrets"),
        )
    )
    with pytest.raises(BlockedUrl):
        fetcher.get("https://example.com/job")


def test_an_allowed_redirect_is_followed():
    fetcher = _fetcher(
        _redirect_then(
            "https://jobs.example.com/real",
            httpx.Response(200, headers={"content-type": "text/html"}, text=SAMPLE_HTML),
        )
    )
    assert "Junior Python Developer" in fetcher.get("https://example.com/job")


def test_a_relative_redirect_resolves_against_the_previous_hop():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/job":
            return httpx.Response(302, headers={"location": "/real"})
        return httpx.Response(200, headers={"content-type": "text/html"}, text=SAMPLE_HTML)

    fetcher = _fetcher(handler)
    assert "Junior Python Developer" in fetcher.get("https://example.com/job")


def test_an_endless_redirect_chain_stops():
    fetcher = _fetcher(lambda r: httpx.Response(302, headers={"location": "https://example.com/x"}))
    with pytest.raises(FetchError, match="too many redirects"):
        fetcher.get("https://example.com/job")


def test_a_redirect_without_a_location_is_an_error():
    fetcher = _fetcher(lambda r: httpx.Response(302))
    with pytest.raises(FetchError, match="without a location"):
        fetcher.get("https://example.com/job")
