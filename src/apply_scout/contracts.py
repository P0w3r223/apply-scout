"""Typed data contracts shared across the agent, its tools, and the eval harness.

These are the nouns the whole project agrees on. Tools emit them, the agent
reasons over them, the harness scores them. Everything here is a frozen Pydantic
model: value objects that are validated at construction and never mutated —
invalid states are rejected at the boundary rather than defended against later.

Nothing here does I/O. Populating these from a live posting, a CV file, or the
GitHub API is the tools' job (later milestones); here we only define the shapes.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    """Base for immutable, strictly-validated value objects.

    `frozen` makes instances hashable and side-effect-free; `extra="forbid"` means a
    typo in a tool's JSON output is a loud validation error, not a silently dropped
    field — which is exactly the failure the eval harness needs to be able to see.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class Importance(StrEnum):
    """How much a requirement matters. Nice-to-haves must not sink a candidate the
    way a missing hard requirement does — the match report weights them differently."""

    REQUIRED = "required"
    NICE_TO_HAVE = "nice_to_have"


class Requirement(_Frozen):
    """A single thing a posting asks for, normalized out of prose."""

    text: str = Field(..., min_length=1, description="The requirement, e.g. 'FastAPI'.")
    importance: Importance = Importance.REQUIRED
    category: str | None = Field(
        None, description="Optional grouping, e.g. 'language', 'framework', 'soft-skill'."
    )


class JobPosting(_Frozen):
    """A structured job posting: the output of `fetch_job_posting`."""

    url: str = Field(..., description="Source URL the posting was fetched from.")
    title: str = Field(..., min_length=1)
    company: str | None = None
    location: str | None = None
    seniority: str | None = Field(None, description="e.g. 'junior', 'mid', 'senior'.")
    requirements: tuple[Requirement, ...] = ()
    salary: str | None = Field(None, description="Raw salary text if present; None if absent.")


class CVProfile(_Frozen):
    """A candidate's CV, parsed into evidence-searchable pieces: the output of `read_cv`."""

    name: str | None = None
    headline: str | None = Field(None, description="One-line self-description, if any.")
    skills: tuple[str, ...] = ()
    experience: tuple[str, ...] = Field(
        (), description="Free-text experience bullets, kept verbatim."
    )
    education: tuple[str, ...] = ()


class EvidenceKind(StrEnum):
    """Where a piece of evidence was found. `NONE` records an honest 'looked, found
    nothing' — absence of evidence is itself a reportable result, not an empty gap."""

    REPO = "repo"
    README = "readme"
    FILE = "file"
    NONE = "none"


class Evidence(_Frozen):
    """A concrete, citable proof (or lack) that the candidate meets a requirement.

    The whole anti-hallucination stance rests on this: a claim in the cover letter is
    only allowed if it traces back to an `Evidence` with a real, checkable `url`.
    """

    requirement: str = Field(..., description="The requirement text this addresses.")
    kind: EvidenceKind
    repo: str | None = Field(None, description="owner/name, if the evidence is in a repo.")
    url: str | None = Field(None, description="Direct link a human can open to verify.")
    snippet: str | None = Field(None, description="Short quoted proof, if applicable.")


class Rating(StrEnum):
    """How well the candidate meets one requirement, judged against the evidence."""

    STRONG = "strong"
    WEAK = "weak"
    NONE = "none"


class MatchAssessment(_Frozen):
    """The verdict for a single requirement: rating + the evidence behind it."""

    requirement: Requirement
    rating: Rating
    evidence: tuple[Evidence, ...] = ()
    rationale: str | None = Field(None, description="One line on why this rating.")


class MatchReport(_Frozen):
    """The agent's headline deliverable: requirement -> evidence -> rating, per item."""

    job_title: str
    job_url: str
    assessments: tuple[MatchAssessment, ...] = ()
    summary: str | None = None


class LetterSentence(_Frozen):
    """One sentence of a cover-letter draft, tagged with its provenance.

    `supported` is set by the guardrail (a later milestone): a sentence that makes a
    factual claim with no backing `Evidence` is flagged so it can be removed. Plain
    connective sentences carry no claim and stay `supported=True` by construction.
    """

    text: str
    supported: bool = True
    evidence_urls: tuple[str, ...] = ()


class CoverLetterDraft(_Frozen):
    """A cover letter assembled strictly from facts already in the match report."""

    sentences: tuple[LetterSentence, ...] = ()
