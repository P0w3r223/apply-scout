"""Run every payload in every placement against the production toolset.

The tools come from `real_tools()` — the same call the CLI makes — so the suite measures the wiring
that ships rather than a hand-assembled imitation of it. Only the two ends are substituted: the
network, by a transport that serves the attacked page and records every address a request was made
to, and the model, by the reader in `obey.py`.

**No network and no key, by construction rather than by cassette.** There is nothing to record here:
the attacker's server is a transport, the reader is a function, and the same grid produces the same
table on any machine. That is also the limit of what the suite can see — an injected client means
`check_resolved` does not run, so the resolving half of the URL policy is covered by unit tests and
not by this table. It is named in the report rather than left for a reader to assume.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import httpx

from apply_scout.attack import pages
from apply_scout.attack.obey import obey
from apply_scout.attack.payloads import METADATA_URL, PAYLOADS, REDIRECT_URL, Payload
from apply_scout.fetch import HttpFetcher, MainTextExtractor, strip_tags
from apply_scout.github import DiskCache, GitHubClient
from apply_scout.tools.real import real_tools
from apply_scout.tools.registry import ToolRegistry

POSTING_URL = "https://jobs.example/senior-python-engineer"
_POSTING_JSON = json.dumps(
    {
        "url": POSTING_URL,
        "title": pages.BASE_TITLE,
        "requirements": [{"text": "Python"}, {"text": "FastAPI"}, {"text": "PostgreSQL"}],
    }
)


class _Fallback:
    """The reading production falls back to when trafilatura returns nothing.

    Not a hypothetical: `extract_main_text` uses it for any template trafilatura cannot parse, and
    the page is written by the attacker. Substituted as an arm rather than provoked with an
    unparseable page, so the two arms differ in the extractor and in nothing else."""

    def extract(self, html: str, url: str = "") -> str:
        return strip_tags(html)


#: The production extractor, and the one production falls back to. Both ship; which runs is decided
#: by whether trafilatura could parse the page it was handed.
ARMS = {"trafilatura": MainTextExtractor, "fallback": _Fallback}


@dataclass(frozen=True, slots=True)
class Attempt:
    """One attacked posting: what was printed on it, and what the harness let happen."""

    arm: str
    payload: str
    leg: str
    placement: str
    #: Whether the injected sentence survived extraction into the text the reader was handed.
    reached: bool
    #: Whether the attacker got what the text asked for, judged by the payload.
    succeeded: bool
    #: Every address a request was actually made to, in order. The audit trail behind `succeeded`.
    requests: tuple[str, ...]


class _Recording:
    """Stands in for the structurer, and keeps the text the reader was handed.

    That text — not the HTML — is what a model would read, so it is the only honest place to ask
    whether a payload arrived."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def to_json(self, *, instructions: str, content: str, schema: dict, model: str) -> str:
        self.seen.append(content)
        return _POSTING_JSON


def _transport(page_html: str, log: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        log.append(str(request.url))
        if str(request.url) == REDIRECT_URL:
            return httpx.Response(302, headers={"location": METADATA_URL})
        if str(request.url) == POSTING_URL:
            return httpx.Response(200, headers={"content-type": "text/html"}, text=page_html)
        # Anything else the reader was told to fetch answers plausibly, so a failure to arrive is
        # the guard's doing and never the fixture's.
        return httpx.Response(
            200, headers={"content-type": "text/html"}, text="<html><body><p>ok</p></body></html>"
        )

    return httpx.MockTransport(handler)


def run_one(payload: Payload, placement: str, *, arm: str, workspace: Path) -> Attempt:
    workspace.mkdir(parents=True, exist_ok=True)
    cv = workspace / "cv.md"
    cv.write_text("Patryk — Python, FastAPI, PostgreSQL.", encoding="utf-8")
    secret = workspace / "id_rsa"
    secret.write_text("-----BEGIN OPENSSH PRIVATE KEY-----", encoding="utf-8")

    log: list[str] = []
    structurer = _Recording()
    registry = ToolRegistry(
        real_tools(
            readable=[cv],
            fetcher=HttpFetcher(client=httpx.Client(transport=_transport(
                pages.page(payload.text, placement), log
            ))),
            structurer=structurer,
            extractor=ARMS[arm](),
            github=GitHubClient(cache=DiskCache(workspace / "cache")),
        )
    )

    contents = [registry.dispatch("fetch_job_posting", {"url": POSTING_URL}).content]
    # A distinctive slice rather than the whole sentence: extraction reflows whitespace, and an
    # equality test would report "did not reach" for text that plainly did.
    needle = payload.text.split(":", 1)[-1].strip()[:40]
    reached = any(needle in seen for seen in structurer.seen)
    contents += obey(payload, registry, secret_path=str(secret), reached=reached)

    return Attempt(
        arm=arm,
        payload=payload.name,
        leg=payload.leg,
        placement=placement,
        reached=reached,
        succeeded=payload.achieved(contents, log),
        requests=tuple(log),
    )


def run(workspace: Path) -> list[Attempt]:
    """The full cross product: every payload, in every placement, under both extractors."""
    return [
        run_one(
            payload,
            placement,
            arm=arm,
            workspace=workspace / f"{arm}-{payload.name}-{placement}",
        )
        for arm in ARMS
        for payload in PAYLOADS
        for placement in pages.PLACEMENTS
    ]
