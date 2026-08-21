"""The real `fetch_job_posting` tool: fetch a URL, extract its text, structure it.

Fetching and structuring are injected (an `HttpFetcher` and a `Structurer`), so the
tool is fully testable with recorded HTTP responses and a scripted structurer — no
network, no key. Any failure along the way (bad URL, empty page, unstructurable text)
comes back as a structured `ToolResult` error the agent can read and react to.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from apply_scout import config
from apply_scout.contracts import JobPosting
from apply_scout.fetch import Extractor, Fetcher, FetchError, MainTextExtractor
from apply_scout.structuring import Structurer, StructuringError, structure
from apply_scout.tools.base import PydanticTool, ToolResult

_INSTRUCTIONS = """You extract a job posting into structured data.

From the page text, produce a JobPosting: title, company, location, seniority, and the \
list of requirements. For each requirement set `importance` to `nice_to_have` only when \
the posting clearly frames it as optional ("nice to have", "a plus"); otherwise \
`required`. Use the exact source URL {url} for the `url` field. Leave any field the \
posting does not mention as null — do not invent details."""


class FetchJobPostingInput(BaseModel):
    url: str = Field(..., description="URL of the job posting to fetch.")


class FetchJobPosting(PydanticTool):
    name = "fetch_job_posting"
    description = "Fetch a job posting from a URL and extract its requirements into a JobPosting."
    input_model = FetchJobPostingInput

    def __init__(
        self,
        *,
        fetcher: Fetcher,
        structurer: Structurer,
        extractor: Extractor | None = None,
        model: str = config.STRUCTURE_MODEL,
        max_attempts: int = config.STRUCTURE_MAX_ATTEMPTS,
    ) -> None:
        self._fetcher = fetcher
        self._structurer = structurer
        self._extractor = extractor or MainTextExtractor()
        self._model = model
        self._max_attempts = max_attempts
        # Every posting this tool returned, in order, for a caller that needs to check a
        # deliverable against its source (see `guardrail.requirement_grounding`). The
        # trajectory only keeps a log-safe summary, so nothing downstream can recover them
        # from there — and a run where this stays empty is a run that never read the ad,
        # which is itself the finding. Same idiom as `SubmitReport.submitted`.
        #
        # All of them, not the last one: the loop re-fetches (the JavaScript-only task calls
        # this tool twice), and if a retry structures to *fewer* requirements than the first
        # attempt, keeping only the newest would score a faithful report against a document
        # the model had already superseded — a maximum fabrication verdict for a correct run.
        self.postings: tuple[JobPosting, ...] = ()

    def _run(self, data: FetchJobPostingInput) -> ToolResult:  # type: ignore[override]
        try:
            html = self._fetcher.get(data.url)
        except FetchError as exc:
            return ToolResult.error(f"Could not fetch the posting: {exc}")

        text = self._extractor.extract(html, data.url)[: config.STRUCTURE_MAX_CHARS]
        if not text:
            return ToolResult.error("The page had no readable text — it may require JavaScript.")

        try:
            posting = structure(
                text,
                JobPosting,
                structurer=self._structurer,
                model=self._model,
                instructions=_INSTRUCTIONS.format(url=data.url),
                max_attempts=self._max_attempts,
            )
        except StructuringError as exc:
            return ToolResult.error(str(exc))

        # Trust our own URL over whatever the model echoed back.
        posting = posting.model_copy(update={"url": data.url})
        self.postings += (posting,)
        return ToolResult.success(
            posting.model_dump_json(),
            summary=f"posting '{posting.title}' with {len(posting.requirements)} requirement(s)",
        )
