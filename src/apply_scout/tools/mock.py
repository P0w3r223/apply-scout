"""Mock tools for the milestone-1 skeleton.

These return fixed, well-formed data so the agent loop can be wired and tested
end-to-end before any real fetching, CV parsing, or GitHub calls exist. They match
the *contracts* the real tools (later milestones) will produce, so swapping a mock
for its real counterpart is a drop-in — the loop and the schema don't change.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from apply_scout.contracts import (
    CVProfile,
    Evidence,
    EvidenceKind,
    Importance,
    JobPosting,
    Requirement,
)
from apply_scout.tools.base import PydanticTool, ToolResult


class FetchJobPostingInput(BaseModel):
    url: str = Field(..., description="URL of the job posting to fetch.")


class MockFetchJobPosting(PydanticTool):
    name = "fetch_job_posting"
    description = "Fetch a job posting from a URL and extract its requirements into a JobPosting."
    input_model = FetchJobPostingInput

    def _run(self, data: FetchJobPostingInput) -> ToolResult:  # type: ignore[override]
        posting = JobPosting(
            url=data.url,
            title="Junior Python Developer",
            company="Acme Sp. z o.o.",
            location="Wrocław (hybrid)",
            seniority="junior",
            requirements=(
                Requirement(text="Python", category="language"),
                Requirement(text="FastAPI", category="framework"),
                Requirement(text="SQL", importance=Importance.NICE_TO_HAVE, category="data"),
            ),
        )
        return ToolResult.success(
            posting.model_dump_json(),
            summary=f"posting '{posting.title}' with {len(posting.requirements)} requirements",
        )


class ReadCVInput(BaseModel):
    path: str = Field(..., description="Path to the candidate's CV file.")


class MockReadCV(PydanticTool):
    name = "read_cv"
    description = "Parse the candidate's CV file into a structured, searchable profile."
    input_model = ReadCVInput

    def _run(self, data: ReadCVInput) -> ToolResult:  # type: ignore[override]
        cv = CVProfile(
            name="Patryk",
            headline="Telecommunications student building data/AI projects in Python.",
            skills=("Python", "FastAPI", "SQL", "scikit-learn", "Docker"),
            experience=(
                "Built car-price-ml: EDA, model bake-off, FastAPI /predict service.",
                "Built ab-lab: A/B statistics package validated by simulation.",
            ),
            education=("Telecommunications (in progress)",),
        )
        return ToolResult.success(
            cv.model_dump_json(),
            summary=f"CV for {cv.name} with {len(cv.skills)} skills",
        )


class GithubEvidenceInput(BaseModel):
    requirement: str = Field(
        ..., description="The requirement to find evidence for, e.g. 'FastAPI'."
    )
    github_user: str = Field(..., description="The candidate's GitHub username.")


class MockGithubEvidence(PydanticTool):
    name = "github_evidence"
    description = (
        "Search the candidate's GitHub repositories for concrete evidence of a requirement "
        "(a repo, README, or file), returning citable links."
    )
    input_model = GithubEvidenceInput

    def _run(self, data: GithubEvidenceInput) -> ToolResult:  # type: ignore[override]
        found = (
            Evidence(
                requirement=data.requirement,
                kind=EvidenceKind.REPO,
                repo=f"{data.github_user}/car-price-ml",
                url=f"https://github.com/{data.github_user}/car-price-ml",
                snippet="FastAPI /predict service with Docker.",
            ),
        )
        payload = {"evidence": [e.model_dump(mode="json") for e in found]}
        return ToolResult.success(
            json.dumps(payload),
            summary=f"{len(found)} evidence item(s) for '{data.requirement}'",
        )


def mock_tools() -> list[PydanticTool]:
    """The three mock tools, ready to hand to a ToolRegistry."""
    return [MockFetchJobPosting(), MockReadCV(), MockGithubEvidence()]
