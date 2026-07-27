"""The GitHub client: pagination, rate limits, README decoding, and caching."""

from __future__ import annotations

import base64

import httpx
import pytest

from apply_scout.github import DiskCache, GitHubClient, GitHubError, GitHubRateLimitError


def _client(handler, **kwargs) -> GitHubClient:
    return GitHubClient(client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


def _repo(name: str) -> dict:
    return {"name": name, "full_name": f"u/{name}", "html_url": f"https://github.com/u/{name}"}


def test_list_repos_follows_pagination():
    page1 = [_repo(f"r{i}") for i in range(100)]  # full page -> there is a page 2
    page2 = [_repo("last")]

    def handler(request):
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, json={1: page1, 2: page2}.get(page, []))

    repos = _client(handler).list_repos("u")
    assert len(repos) == 101
    assert repos[-1].name == "last"


def test_list_repos_user_not_found_raises():
    client = _client(lambda r: httpx.Response(404, json={"message": "Not Found"}))
    with pytest.raises(GitHubError):
        client.list_repos("ghost")


def test_rate_limit_raises():
    client = _client(
        lambda r: httpx.Response(
            403, headers={"X-RateLimit-Remaining": "0"}, json={"message": "rl"}
        )
    )
    with pytest.raises(GitHubRateLimitError):
        client.list_repos("u")


def test_get_readme_decodes_base64():
    content = base64.b64encode(b"A FastAPI /predict service with Docker.").decode()
    client = _client(
        lambda r: httpx.Response(
            200,
            json={
                "content": content,
                "encoding": "base64",
                "html_url": "https://github.com/u/r/blob/main/README.md",
            },
        )
    )
    readme = client.get_readme("u", "r")
    assert readme is not None
    assert "FastAPI" in readme.text
    assert readme.html_url.endswith("README.md")


def test_get_readme_missing_returns_none():
    client = _client(lambda r: httpx.Response(404, json={"message": "Not Found"}))
    assert client.get_readme("u", "r") is None


def test_disk_cache_roundtrip(tmp_path):
    cache = DiskCache(tmp_path)
    assert cache.get("https://example/x") is None
    cache.set("https://example/x", "value")
    assert cache.get("https://example/x") == "value"


def test_cache_avoids_second_request(tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=[_repo("only")])  # single repo -> one page

    client = _client(handler, cache=DiskCache(tmp_path))
    client.list_repos("u")
    client.list_repos("u")  # identical URL -> served from disk cache
    assert calls["n"] == 1
