"""Fetching a URL and extracting its readable text.

Two small, testable pieces: `HttpFetcher` (httpx, with an injectable client so tests
use recorded responses via `httpx.MockTransport`), and `extract_main_text` (trafilatura
for real content extraction, with a stdlib fallback so a page trafilatura can't parse
still yields text rather than nothing). Network and parsing are kept apart from the
LLM structuring that follows.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Protocol, runtime_checkable

import httpx

from apply_scout import config


class FetchError(Exception):
    """Raised when a URL cannot be fetched into usable HTML (network, status, type)."""


@runtime_checkable
class Fetcher(Protocol):
    """What the posting tool needs from the network: a URL in, HTML out.

    Narrow on purpose — it is the seam a recording/replaying wrapper substitutes for, so
    the same tool code runs live or entirely offline."""

    def get(self, url: str) -> str: ...


@runtime_checkable
class Extractor(Protocol):
    """HTML in, readable main text out — the seam between fetching and structuring.

    Split out from `extract_main_text` as an injectable dependency because extraction is
    not as reproducible as it looks: trafilatura's output shifts between its own versions
    and between libxml2 builds, so the same recorded HTML yields different text on another
    machine. A replay that re-ran extraction locally would key its structuring request off
    that different text and miss every recorded entry — which is exactly what a CI runner
    with a newer trafilatura did. Recording this seam makes the offline run depend on the
    page, not on the environment that reads it."""

    def extract(self, html: str, url: str = "") -> str: ...


class MainTextExtractor:
    """The production extractor: trafilatura, with the stdlib fallback behind it.

    `url` is accepted for the recorder's benefit (it labels the entry) and ignored here —
    extraction depends on the markup alone."""

    def extract(self, html: str, url: str = "") -> str:
        return extract_main_text(html)


class HttpFetcher:
    """Fetches a URL and returns its HTML text.

    Pass a preconfigured `httpx.Client` (e.g. with a `MockTransport`) for tests; leave
    it out for real use and a client is created and closed per call."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def get(self, url: str) -> str:
        owns_client = self._client is None
        client = self._client or httpx.Client(
            timeout=config.HTTP_TIMEOUT_S,
            follow_redirects=True,
            headers={"User-Agent": config.HTTP_USER_AGENT},
        )
        try:
            response = client.get(url)
        except httpx.HTTPError as exc:
            raise FetchError(f"request failed: {exc}") from exc
        finally:
            if owns_client:
                client.close()

        if response.status_code != 200:
            raise FetchError(f"HTTP {response.status_code}")
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type and "text" not in content_type:
            raise FetchError(f"unexpected content-type: {content_type or 'unknown'}")
        return response.text[: config.HTTP_MAX_HTML_CHARS]


class _TextExtractor(HTMLParser):
    """Minimal stdlib fallback: collect visible text, skipping script/style."""

    _SKIP = {"script", "style", "noscript", "template"}

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP:
            self._skipping += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skipping:
            self._skipping -= 1

    def handle_data(self, data: str) -> None:
        if not self._skipping and data.strip():
            self._chunks.append(data.strip())

    def text(self) -> str:
        return "\n".join(self._chunks)


def _strip_tags(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.text()


def extract_main_text(html: str) -> str:
    """Extract the readable main text from an HTML page.

    Tries trafilatura (good at dropping nav/boilerplate); falls back to a stdlib tag
    strip when trafilatura returns nothing (a template it can't parse). Returns an
    empty string only when the page genuinely has no text (e.g. a JS-only shell)."""
    try:
        import trafilatura  # imported lazily: only the fetch tool needs it
    except ImportError:  # pragma: no cover - trafilatura is a declared dependency
        return _strip_tags(html)

    extracted = trafilatura.extract(html, include_comments=False, include_tables=True)
    if extracted and extracted.strip():
        return extracted.strip()
    return _strip_tags(html)
