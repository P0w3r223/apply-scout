"""A small GitHub API client for the evidence tool: list a user's repos, read a
README, with pagination, rate-limit awareness, and an on-disk cache.

Kept deliberately narrow (two read endpoints) and dependency-injectable: pass an
`httpx.Client` (tests use `MockTransport`) and a `Cache`, so the whole thing runs
offline in tests. `GITHUB_TOKEN` from the environment raises the rate limit but is
never required.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, ConfigDict

from apply_scout import config


class GitHubError(Exception):
    """A GitHub request failed (not-found, bad status, transport)."""


class GitHubRateLimitError(GitHubError):
    """The GitHub rate limit was hit — the caller should back off, not retry now."""


@runtime_checkable
class Cache(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...


class NullCache:
    """No caching — used in tests where each request must reach the transport."""

    def get(self, key: str) -> str | None:
        return None

    def set(self, key: str, value: str) -> None:
        return None


class DiskCache:
    """A trivial key→file cache. Keys are hashed so any URL is a safe filename."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return self._root / f"{digest}.json"

    def get(self, key: str) -> str | None:
        path = self._path(key)
        return path.read_text(encoding="utf-8") if path.exists() else None

    def set(self, key: str, value: str) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        self._path(key).write_text(value, encoding="utf-8")


class Repo(BaseModel):
    """The bits of a GitHub repo the evidence search looks at."""

    model_config = ConfigDict(frozen=True)

    name: str
    full_name: str  # owner/name
    html_url: str
    description: str | None = None
    language: str | None = None
    topics: tuple[str, ...] = ()
    default_branch: str = "main"


@dataclass(frozen=True)
class ReadmeDoc:
    """A repo's README text plus the human-openable link to it."""

    text: str
    html_url: str


class GitHubClient:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        token: str | None = None,
        cache: Cache | None = None,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._token = token if token is not None else os.getenv("GITHUB_TOKEN")
        self._cache = cache or NullCache()

    def _ensure_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=config.HTTP_TIMEOUT_S, follow_redirects=True)
        return self._client

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": config.HTTP_USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _get_json(self, url: str) -> Any | None:
        """GET a URL and return parsed JSON, None on 404. Caches 200s; maps rate limits."""
        cached = self._cache.get(url)
        if cached is not None:
            return json.loads(cached)

        client = self._ensure_client()
        try:
            response = client.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            raise GitHubError(f"request failed: {exc}") from exc

        if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
            raise GitHubRateLimitError("primary rate limit exceeded")
        if response.status_code == 429:
            raise GitHubRateLimitError("secondary rate limit exceeded")
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise GitHubError(f"HTTP {response.status_code}")

        self._cache.set(url, response.text)
        return response.json()

    def list_repos(self, user: str) -> list[Repo]:
        """All public repos for a user, following pagination."""
        repos: list[Repo] = []
        page = 1
        while True:
            url = (
                f"{config.GITHUB_API_BASE}/users/{user}/repos"
                f"?per_page={config.GITHUB_PER_PAGE}&page={page}&sort=updated"
            )
            data = self._get_json(url)
            if data is None:
                raise GitHubError(f"user not found: {user}")
            if not data:
                break
            repos.extend(
                Repo(
                    name=item["name"],
                    full_name=item["full_name"],
                    html_url=item["html_url"],
                    description=item.get("description"),
                    language=item.get("language"),
                    topics=tuple(item.get("topics") or ()),
                    default_branch=item.get("default_branch", "main"),
                )
                for item in data
            )
            if len(data) < config.GITHUB_PER_PAGE:
                break
            page += 1
        return repos

    def get_readme(self, owner: str, repo: str) -> ReadmeDoc | None:
        """The repo's README as text, or None if it has none (a valid, non-fatal case)."""
        url = f"{config.GITHUB_API_BASE}/repos/{owner}/{repo}/readme"
        data = self._get_json(url)
        if data is None:
            return None
        content = data.get("content", "")
        if data.get("encoding") == "base64":
            text = base64.b64decode(content).decode("utf-8", errors="replace")
        else:
            text = content
        html_url = data.get("html_url") or f"https://github.com/{owner}/{repo}"
        return ReadmeDoc(text=text, html_url=html_url)
