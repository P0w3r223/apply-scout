"""The tool the agent finishes with: hand back the deliverable as a contract.

Without this, the loop's output is a wall of markdown. That is fine for a human reader
and useless to the harness, which scores `MatchReport` and `CoverLetterDraft` — so the
loop could never be measured on the same axes as the deterministic pipeline, and the
project's headline comparison had nothing to compare (ADR-0006).

Making the *finish* a tool call rather than a free-text turn is the standard agentic
answer, and it costs nothing extra: the loop already validates every tool's arguments
against a Pydantic schema and hands failures back as recoverable errors, so a malformed
report is a retry the model can act on rather than a parse failure downstream.

The tool deliberately does no work beyond validating and holding the payload. The
guardrail runs *outside* it, exactly as it does in the pipeline — the agent must not be
able to mark its own homework.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from apply_scout.contracts import CoverLetterDraft, MatchReport
from apply_scout.tools.base import PydanticTool, ToolResult


class SubmitReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report: MatchReport = Field(..., description="Every requirement, its rating and its evidence.")
    letter: CoverLetterDraft = Field(
        ...,
        description=(
            "A short cover-letter draft. Every sentence making a factual claim must carry the "
            "evidence_urls that back it, copied from the report — unbacked sentences are removed."
        ),
    )


class SubmitReport(PydanticTool):
    """Terminal tool: records the finished deliverable for the caller to read off."""

    name = "submit_report"
    description = (
        "Submit the finished match report and cover-letter draft. Call this exactly once, "
        "after you have gathered evidence for every requirement, instead of writing the "
        "report as a normal message. Rate each requirement strong / weak / none, and attach "
        "the evidence you actually retrieved — a requirement with no evidence is rated none."
    )
    input_model = SubmitReportInput

    def __init__(self) -> None:
        # The submission is read by the caller after the run; None means the loop ended
        # without ever producing a deliverable, which the harness scores as not-completed.
        self.submitted: SubmitReportInput | None = None

    def _run(self, data: BaseModel) -> ToolResult:
        assert isinstance(data, SubmitReportInput)  # guaranteed by PydanticTool.run
        self.submitted = data
        rated = len(data.report.assessments)
        sentences = len(data.letter.sentences)
        return ToolResult.success(
            content=(
                f"Report received: {rated} requirement(s) rated, {sentences} letter "
                "sentence(s). Nothing further is needed — stop here."
            ),
            summary=f"submitted: {rated} rating(s), {sentences} letter sentence(s)",
        )
