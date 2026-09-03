"""Fetching a URL and extracting its readable text.

Two small, testable pieces: `HttpFetcher` (httpx, with an injectable client so tests
use recorded responses via `httpx.MockTransport`), and `extract_main_text` (trafilatura
for real content extraction, with a stdlib fallback so a page trafilatura can't parse
still yields text rather than nothing). Network and parsing are kept apart from the
LLM structuring that follows.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Protocol, runtime_checkable
from urllib.parse import urljoin, urlsplit

import httpx

from apply_scout import config


class FetchError(Exception):
    """Raised when a URL cannot be fetched into usable HTML (network, status, type)."""


class BlockedUrl(FetchError):
    """Raised when a URL is refused by policy, before any request is made.

    A `FetchError` subclass on purpose: the tool layer already turns `FetchError` into a
    structured `ToolResult.error`, so a refusal reaches the model as a normal tool failure
    rather than as an exception through the loop."""


def check_url(url: str) -> None:
    """Refuse a URL on what the string alone shows. Resolves nothing, touches no network.

    This is the half of the policy that can run *everywhere* — at the `Fetcher` seam, in every
    cassette mode, and in offline tests — because DNS is a network call and `replay` is
    guaranteed not to make one. The resolving half is `check_resolved`, applied where a
    connection is about to happen anyway."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in config.HTTP_ALLOWED_SCHEMES:
        raise BlockedUrl(f"scheme not allowed: {scheme or 'none'}")
    if parts.username or parts.password:
        # Credentials in the URL are never needed for a public posting, and they are how a
        # crafted address smuggles a secret into somebody else's access log.
        raise BlockedUrl("credentials in URL")
    host = parts.hostname
    if not host:
        raise BlockedUrl("no host in URL")
    if host == "localhost" or host.endswith(".localhost"):
        raise BlockedUrl(f"loopback host: {host}")
    literal = _as_ip(host)
    if literal is not None and not _is_public(literal):
        raise BlockedUrl(f"non-public address: {literal}")


def check_resolved(url: str, *, resolve: Callable[[str], list[str]] | None = None) -> None:
    """Refuse a URL whose host resolves anywhere that is not public.

    Every address the name resolves to has to be public, not merely the first: a name with one
    public and one loopback record would otherwise pass and then connect to the loopback one.

    The gap this leaves is named rather than papered over — the name is resolved here and
    resolved again by the client when it connects, so a DNS answer that changes between the two
    is not caught. Closing that needs the connection pinned to the address that was checked;
    the README's Limitations records it."""
    host = urlsplit(url).hostname
    if not host or _as_ip(host) is not None:
        return  # no name to resolve — `check_url` has already judged the literal
    resolver = resolve or _resolve
    try:
        addresses = resolver(host)
    except OSError as exc:
        raise BlockedUrl(f"host does not resolve: {host}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not _is_public(ip):
            raise BlockedUrl(f"{host} resolves to a non-public address: {ip}")


def _resolve(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)]


def _as_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """The host as an IP address if it is written as one, else None."""
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Whether an address is one this project may talk to.

    `is_global` already excludes private, loopback, link-local, reserved, multicast and
    unspecified ranges — including `169.254.169.254`, the cloud metadata address that is the
    canonical target here. IPv4-mapped IPv6 is unwrapped first, because `::ffff:127.0.0.1`
    is loopback written the other way round."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global


class GuardedFetcher:
    """A `Fetcher` that applies the URL policy before the inner fetcher sees the address.

    Composed *outside* the cassette so it runs in every mode — `off`, `record`, `replay` and
    `auto`. That placement is the point: CI runs `replay` and nothing else, so a guard sitting
    inside `HttpFetcher` would never execute in the only mode the build exercises."""

    def __init__(self, inner: Fetcher, *, check: Callable[[str], None] = check_url) -> None:
        self._inner = inner
        self._check = check

    def get(self, url: str) -> str:
        self._check(url)
        return self._inner.get(url)


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
            follow_redirects=False,
            headers={"User-Agent": config.HTTP_USER_AGENT},
        )
        try:
            response = self._follow(client, url, resolves=owns_client)
        finally:
            if owns_client:
                client.close()

        if response.status_code != 200:
            raise FetchError(f"HTTP {response.status_code}")
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type and "text" not in content_type:
            raise FetchError(f"unexpected content-type: {content_type or 'unknown'}")
        return response.text[: config.HTTP_MAX_HTML_CHARS]

    def _follow(self, client: httpx.Client, url: str, *, resolves: bool) -> httpx.Response:
        """Walk the redirect chain by hand so every hop is judged before it is requested.

        httpx would follow the chain internally and hand back only the final response, which
        means the address that was checked is not the address that was fetched — a redirect is
        the ordinary way an allowed URL turns into a forbidden one, and it is the vector this
        whole guard exists for.

        `resolves` is on only when this fetcher owns its client. An injected client has had its
        transport substituted, so no socket is opened and there is nothing to resolve *to*;
        resolving anyway would make every offline test perform DNS, which is the property
        `replay` is built to guarantee. The name-free half of the policy runs on every hop
        regardless, so a redirect to a literal internal address is refused in both cases."""
        for _ in range(config.HTTP_MAX_REDIRECTS + 1):
            check_url(url)
            if resolves:
                check_resolved(url)
            try:
                response = client.get(url)
            except httpx.HTTPError as exc:
                raise FetchError(f"request failed: {exc}") from exc
            if not response.is_redirect:
                return response
            location = response.headers.get("location", "")
            if not location:
                raise FetchError(f"HTTP {response.status_code} without a location")
            url = urljoin(url, location)
        raise FetchError(f"too many redirects (over {config.HTTP_MAX_REDIRECTS})")


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
