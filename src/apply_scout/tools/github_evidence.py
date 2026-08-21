"""The real `github_evidence` tool: find citable proof of a requirement in a user's
GitHub repos.

`find_evidence` is a pure function (repos + READMEs in, Evidence out) so the matching
logic is unit-tested without any network. The tool wraps it with a `GitHubClient`
(injectable), and a missing README or a rate-limit mid-scan is handled gracefully —
absence of evidence is itself a reported result (`Rating`/`EvidenceKind.NONE`).
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from apply_scout import config
from apply_scout.contracts import Evidence, EvidenceKind
from apply_scout.github import GitHubClient, GitHubError, GitHubRateLimitError, ReadmeDoc, Repo
from apply_scout.tools.base import PydanticTool, ToolResult


def _first_line_with(text: str, needle: str) -> str:
    """Return the first line containing `needle` (case-insensitive), trimmed for a log/snippet."""
    for line in text.splitlines():
        if needle in line.lower():
            trimmed = line.strip()
            return trimmed[:200]
    return ""


def find_evidence(
    requirement: str,
    repos: list[Repo],
    readmes: dict[str, ReadmeDoc | None],
) -> list[Evidence]:
    """Match a requirement against repo metadata and README text.

    Prefers a README hit (it carries a quotable snippet) over a metadata-only hit. If
    nothing matches anywhere, returns a single `NONE` evidence — an explicit 'looked,
    found nothing', not an empty gap."""
    needle = requirement.strip().lower()
    found: list[Evidence] = []

    for repo in repos:
        readme = readmes.get(repo.full_name)
        if readme is not None and needle in readme.text.lower():
            found.append(
                Evidence(
                    requirement=requirement,
                    kind=EvidenceKind.README,
                    repo=repo.full_name,
                    url=readme.html_url,
                    snippet=_first_line_with(readme.text, needle),
                )
            )
            continue

        haystack = " ".join(
            part
            for part in (repo.name, repo.description, repo.language, " ".join(repo.topics))
            if part
        ).lower()
        if needle in haystack:
            found.append(
                Evidence(
                    requirement=requirement,
                    kind=EvidenceKind.REPO,
                    repo=repo.full_name,
                    url=repo.html_url,
                    snippet=repo.description,
                )
            )

    if not found:
        found.append(Evidence(requirement=requirement, kind=EvidenceKind.NONE))
    return found


class GithubEvidenceInput(BaseModel):
    requirement: str = Field(
        ..., description="The requirement to find evidence for, e.g. 'FastAPI'."
    )
    github_user: str = Field(..., description="The candidate's GitHub username.")


class GithubEvidence(PydanticTool):
    name = "github_evidence"
    description = (
        "Search the candidate's GitHub repositories for concrete evidence of a requirement "
        "(a repo or its README), returning citable links."
    )
    input_model = GithubEvidenceInput

    def __init__(self, *, client: GitHubClient, max_repos: int = config.GITHUB_MAX_REPOS) -> None:
        self._client = client
        self._max_repos = max_repos
        # Every piece of evidence this tool ever handed back, for a caller that needs to check
        # a report's citations against what was actually retrieved (see
        # `guardrail.evidence_grounding`). Same idiom as `FetchJobPosting.postings` and
        # `SubmitReport.submitted`: the trajectory keeps only a log-safe count, so this is the
        # only way to recover what the model was given.
        self.returned: tuple[Evidence, ...] = ()

    def _run(self, data: GithubEvidenceInput) -> ToolResult:  # type: ignore[override]
        try:
            repos = self._client.list_repos(data.github_user)
        except GitHubRateLimitError as exc:
            return ToolResult.error(f"GitHub rate limit reached: {exc}")
        except GitHubError as exc:
            return ToolResult.error(f"GitHub lookup failed: {exc}")

        readmes: dict[str, ReadmeDoc | None] = {}
        for repo in repos[: self._max_repos]:
            owner, _, name = repo.full_name.partition("/")
            try:
                readmes[repo.full_name] = self._client.get_readme(owner, name)
            except GitHubRateLimitError:
                break  # partial scan is fine — evaluate what we have
            except GitHubError:
                readmes[repo.full_name] = None  # a repo README we couldn't read is just "no README"

        evidence = find_evidence(data.requirement, repos, readmes)
        self.returned += tuple(evidence)
        payload = {"evidence": [e.model_dump(mode="json") for e in evidence]}
        found = sum(1 for e in evidence if e.kind is not EvidenceKind.NONE)
        return ToolResult.success(
            json.dumps(payload),
            summary=f"{found} evidence item(s) for '{data.requirement}'",
        )
