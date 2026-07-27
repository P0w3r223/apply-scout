"""Evidence matching (pure) and the github_evidence tool end to end (with recorded HTTP)."""

from __future__ import annotations

import base64
import json

import httpx

from apply_scout.contracts import EvidenceKind
from apply_scout.github import GitHubClient, ReadmeDoc, Repo
from apply_scout.tools.github_evidence import GithubEvidence, find_evidence


def _repo(name: str, **kwargs) -> Repo:
    return Repo(name=name, full_name=f"u/{name}", html_url=f"https://github.com/u/{name}", **kwargs)


def test_find_evidence_prefers_readme_with_snippet():
    repos = [_repo("car-price-ml", language="Python")]
    readmes = {
        "u/car-price-ml": ReadmeDoc(
            text="Serves predictions via a FastAPI /predict endpoint with Docker.",
            html_url="https://github.com/u/car-price-ml/blob/main/README.md",
        )
    }
    evidence = find_evidence("FastAPI", repos, readmes)
    assert len(evidence) == 1
    assert evidence[0].kind is EvidenceKind.README
    assert "FastAPI" in (evidence[0].snippet or "")
    assert (evidence[0].url or "").endswith("README.md")


def test_find_evidence_falls_back_to_metadata():
    repos = [_repo("fastapi-demo", description="A tiny FastAPI service")]
    evidence = find_evidence("FastAPI", repos, {"u/fastapi-demo": None})
    assert evidence[0].kind is EvidenceKind.REPO
    assert evidence[0].url == "https://github.com/u/fastapi-demo"


def test_find_evidence_reports_none_when_absent():
    repos = [_repo("notes", description="just notes")]
    evidence = find_evidence("Kubernetes", repos, {"u/notes": None})
    assert len(evidence) == 1
    assert evidence[0].kind is EvidenceKind.NONE


def test_tool_handles_repo_without_readme():
    readme_content = base64.b64encode(b"Built with FastAPI.").decode()

    def handler(request):
        path = request.url.path
        if path.endswith("/repos"):  # /users/u/repos
            page = int(request.url.params.get("page", "1"))
            if page == 1:
                return httpx.Response(
                    200,
                    json=[
                        {"name": "api", "full_name": "u/api", "language": "Python",
                         "html_url": "https://github.com/u/api"},
                        {"name": "scratch", "full_name": "u/scratch",
                         "html_url": "https://github.com/u/scratch"},
                    ],
                )
            return httpx.Response(200, json=[])
        if path == "/repos/u/api/readme":
            return httpx.Response(
                200,
                json={"content": readme_content, "encoding": "base64",
                      "html_url": "https://github.com/u/api/blob/main/README.md"},
            )
        if path == "/repos/u/scratch/readme":
            return httpx.Response(404, json={"message": "Not Found"})  # no README — must not crash
        return httpx.Response(404, json={"message": "Not Found"})

    client = GitHubClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = GithubEvidence(client=client).run({"requirement": "FastAPI", "github_user": "u"})

    assert result.ok
    kinds = [item["kind"] for item in json.loads(result.content)["evidence"]]
    assert "readme" in kinds  # found in u/api's README; u/scratch's missing README was fine


def test_tool_reports_rate_limit_as_structured_error():
    client = GitHubClient(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    403, headers={"X-RateLimit-Remaining": "0"}, json={"message": "rl"}
                )
            )
        )
    )
    result = GithubEvidence(client=client).run({"requirement": "X", "github_user": "u"})
    assert not result.ok
    assert "rate limit" in result.content.lower()
