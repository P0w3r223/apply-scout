"""HTTP fetching and content extraction, driven by recorded responses."""

from __future__ import annotations

import httpx
import pytest

from apply_scout.fetch import FetchError, HttpFetcher, extract_main_text

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
